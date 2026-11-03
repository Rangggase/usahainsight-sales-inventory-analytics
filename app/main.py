"""UsahaInsight web application. Local-first FastAPI / Jinja2 / SQLite MVP."""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from uuid import uuid4
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import connection, init_db, database_path
from app.services.auth import (setup_schema, has_admin, authenticate, create_session,
    get_session, revoke_session, secure_cookie, csrf_matches, COOKIE_NAME, LOGIN_CSRF_COOKIE,
    SESSION_HOURS)
import secrets
from app.demo import DATA_PATH, seed_when_empty
from app.services.analytics import dashboard, inventory_rows, transactions_list, slow_moving, report_lines
from app.services.importers import DataValidationError, import_products, import_sales, restock
from app.services.reports import sales_csv, sales_xlsx
from app.services.products import (list_products, get_product, create_product, update_product,
                                   archive_product, restore_product)
from app.services.sales import create_sale, sale_product_options, transaction_detail
from app.services.audit import ACTIONS, list_events
from app.services.inventory_intelligence import (analyze_inventory, intelligence_csv,
                                                  intelligence_xlsx, WINDOWS, FILTERS)

from app.services.restock_planner import (
    restock_recommendations, save_reorder_settings, restock_csv, restock_xlsx, STATUSES,
)

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_when_empty()
    setup_schema()
    yield


app = FastAPI(title="UsahaInsight", version="1.4b.0", lifespan=lifespan, docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
def auth_context(request: Request):
    u = getattr(request.state, 'user', None)
    return {'csrf_token': u['csrf_token'] if u else '',
            'current_user': u['username'] if u else ''}

templates = Jinja2Templates(directory=APP_DIR / "templates", context_processors=[auth_context])


@app.middleware('http')
async def guard_authenticated(request: Request, call_next):
    """Protect all application pages, downloads and API schema by default."""
    path = request.url.path
    if path.startswith('/static/') or path in {'/health', '/login'}:
        return await call_next(request)
    user = get_session(request.cookies.get(COOKIE_NAME, ''))
    if not user:
        if request.method in {'GET', 'HEAD'}:
            return RedirectResponse('/login', status_code=303)
        return Response('Login diperlukan.', status_code=401, media_type='text/plain')
    request.state.user = user
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


async def csrf_guard(request: Request):
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail='Login diperlukan.')
    form = await request.form()
    if not csrf_matches(form.get('csrf_token'), user['csrf_token']):
        raise HTTPException(status_code=403, detail='Token CSRF tidak valid. Muat ulang halaman.')


def _login_form_response(request: Request, token: str, error: str = '', status_code: int = 200):
    """Always render a usable form, including after a rejected CSRF submission."""
    response = templates.TemplateResponse(request, 'login.html',
        {'title': 'Masuk', 'login_csrf': token, 'error': error,
         'setup_needed': not has_admin()}, status_code=status_code)
    response.set_cookie(LOGIN_CSRF_COOKIE, token, httponly=True,
                        secure=secure_cookie(), samesite='lax', max_age=1800, path='/')
    # Clear the legacy cookie name to avoid old browser sessions colliding.
    response.delete_cookie('ui_login_csrf', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if get_session(request.cookies.get(COOKIE_NAME, '')):
        return RedirectResponse('/', status_code=303)
    # Reuse a current login token: opening a second login tab must not invalidate
    # the first tab's form. The previous implementation rotated on every GET.
    token = request.cookies.get(LOGIN_CSRF_COOKIE, '')
    if not token or len(token) < 32 or len(token) > 128 or not token.replace('-', '').replace('_', '').isalnum():
        token = secrets.token_urlsafe(32)
    return _login_form_response(request, token)


@app.post('/login')
def login_submit(request: Request, username: str = Form(''), password: str = Form(''),
                       csrf_token: str = Form('')):
    cookie = request.cookies.get(LOGIN_CSRF_COOKIE, '')
    if not cookie or not csrf_matches(csrf_token, cookie):
        if not cookie:
            message = ('Cookie keamanan login tidak dikirim oleh browser. Izinkan cookie '
                       'untuk 127.0.0.1, gunakan satu alamat yang sama, dan coba lagi.')
        elif not csrf_token:
            message = 'Token keamanan formulir tidak terkirim. Muat ulang dan coba lagi.'
        else:
            message = ('Token keamanan tidak cocok, misalnya karena formulir lama atau '
                       'beberapa tab login. Formulir telah diperbarui, silakan coba lagi.')
        return _login_form_response(request, secrets.token_urlsafe(32), message, status_code=403)
    user_id = authenticate(username.strip(), password)
    if not user_id:
        return _login_form_response(
            request, secrets.token_urlsafe(32),
            'Username atau password tidak benar, atau akun terkunci sementara.',
            status_code=401)
    token = create_session(user_id)
    response = RedirectResponse('/', status_code=303)
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=secure_cookie(),
                        samesite='strict', max_age=SESSION_HOURS*3600, path='/')
    response.delete_cookie(LOGIN_CSRF_COOKIE, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/logout', dependencies=[Depends(csrf_guard)])
def logout(request: Request):
    revoke_session(request.cookies.get(COOKIE_NAME, ''))
    response = RedirectResponse('/login', status_code=303)
    response.delete_cookie(COOKIE_NAME, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


def rupiah(value):
    return "Rp " + format(int(value or 0), ",").replace(",", ".")


def compact_rupiah(value):
    value = int(value or 0)
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.1f} M"
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f} jt"
    if value >= 1_000:
        return f"{value/1_000:.0f} rb"
    return str(value)


templates.env.filters["idr"] = rupiah
templates.env.filters["idr_compact"] = compact_rupiah


def page(request, name, **data):
    data["demo_mode"] = not (database_path().parent / ".start_empty").exists()
    return templates.TemplateResponse(request, name, data)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, period: str = "all"):
    if period not in ("all", "7", "30", "90"):
        period = "all"
    data = dashboard(period)
    return page(request, "dashboard.html", active="dashboard", title="Dashboard", data=data)


def product_form_values(sku="", name="", category="", unit_price="0", min_stock="0", initial_stock="0"):
    return {"sku": sku, "name": name, "category": category, "unit_price": unit_price,
            "min_stock": min_stock, "initial_stock": initial_stock}


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request, q: str = "", status: str = "active", success: str = "", error: str = ""):
    if status not in ("active", "archived"):
        status = "active"
    return page(request, "products.html", active="products", title="Produk",
                rows=list_products(q, status=status), q=q, status=status,
                success=success, error=error)


@app.get("/products/new", response_class=HTMLResponse)
def product_new_page(request: Request):
    return page(request, "product_form.html", active="products", title="Tambah Produk",
                editing=False, product=None, form=product_form_values(), errors=[])


@app.post("/products/new", response_class=HTMLResponse, dependencies=[Depends(csrf_guard)])
def product_create(request: Request, sku: str = Form(""), name: str = Form(""),
                   category: str = Form(""), unit_price: str = Form(""),
                   min_stock: str = Form(""), initial_stock: str = Form("")):
    try:
        create_product(sku, name, category, unit_price, min_stock, initial_stock,
                       actor_id=request.state.user['id'])
        return RedirectResponse("/products?success=" + quote("Produk berhasil ditambahkan."), status_code=303)
    except DataValidationError as exc:
        return templates.TemplateResponse(request, "product_form.html",
            {"active": "products", "title": "Tambah Produk", "editing": False, "product": None,
             "form": product_form_values(sku,name,category,unit_price,min_stock,initial_stock),
             "errors": exc.errors, "demo_mode": not (database_path().parent / ".start_empty").exists()},
            status_code=422)


@app.get("/products/{product_id}/edit", response_class=HTMLResponse)
def product_edit_page(request: Request, product_id: int):
    p = get_product(product_id)
    if not p:
        return Response("Produk tidak ditemukan.", status_code=404)
    if not p["is_active"]:
        return RedirectResponse("/products?status=archived&error=" + quote("Aktifkan dahulu produk yang diarsipkan."), status_code=303)
    return page(request, "product_form.html", active="products", title="Edit Produk", editing=True,
                product=p, form=product_form_values(**{k: p[k] for k in ("sku","name","category","unit_price","min_stock")}),
                errors=[])


@app.post("/products/{product_id}/edit", response_class=HTMLResponse, dependencies=[Depends(csrf_guard)])
def product_edit(request: Request, product_id: int, name: str = Form(""),
                 category: str = Form(""), unit_price: str = Form(""), min_stock: str = Form("")):
    p = get_product(product_id)
    if not p:
        return Response("Produk tidak ditemukan.", status_code=404)
    try:
        update_product(product_id, name, category, unit_price, min_stock,
                       actor_id=request.state.user['id'])
        return RedirectResponse("/products?success=" + quote("Perubahan produk berhasil disimpan."), status_code=303)
    except DataValidationError as exc:
        return templates.TemplateResponse(request, "product_form.html",
            {"active": "products", "title": "Edit Produk", "editing": True, "product": p,
             "form": product_form_values(p["sku"],name,category,unit_price,min_stock),
             "errors": exc.errors, "demo_mode": not (database_path().parent / ".start_empty").exists()},
            status_code=422)


@app.post("/products/{product_id}/archive", dependencies=[Depends(csrf_guard)])
def product_archive(request: Request, product_id: int):
    try:
        archive_product(product_id, actor_id=request.state.user['id'])
        return RedirectResponse("/products?success=" + quote("Produk berhasil diarsipkan; histori penjualan tetap tersimpan."), status_code=303)
    except DataValidationError as exc:
        return RedirectResponse("/products?error=" + quote("; ".join(exc.errors)), status_code=303)


@app.post("/products/{product_id}/restore", dependencies=[Depends(csrf_guard)])
def product_restore(request: Request, product_id: int):
    try:
        restore_product(product_id, actor_id=request.state.user['id'])
        return RedirectResponse("/products?success=" + quote("Produk berhasil diaktifkan kembali."), status_code=303)
    except DataValidationError as exc:
        return RedirectResponse("/products?status=archived&error=" + quote("; ".join(exc.errors)), status_code=303)


@app.get("/inventory", response_class=HTMLResponse)
def inventory(request: Request, q: str = "", success: str = "", error: str = ""):
    rows = inventory_rows(q)
    return page(request, "inventory.html", active="inventory", title="Persediaan", products=rows,
                q=q, success=success, error=error, low_count=sum(p["current_stock"] <= p["min_stock"] for p in rows))


@app.post("/inventory/{product_id}/restock", dependencies=[Depends(csrf_guard)])
def add_stock(request: Request, product_id: int, quantity: str = Form(...), note: str = Form("")):
    try:
        qty = int(quantity)
        restock(product_id, qty, note.strip(), actor_id=request.state.user['id'])
        return RedirectResponse(url="/inventory?success=" + quote(f"Berhasil menambah {qty} unit stok."), status_code=303)
    except (DataValidationError, ValueError) as exc:
        msg = "; ".join(exc.errors) if isinstance(exc, DataValidationError) else "Jumlah stok harus bilangan bulat."
        return RedirectResponse(url="/inventory?error=" + quote(msg), status_code=303)


@app.get("/transactions", response_class=HTMLResponse)
def transactions(request: Request, q: str = ""):
    rows = transactions_list(q)
    return page(request, "transactions.html", active="transactions", title="Transaksi", rows=rows, q=q)


def manual_sale_context(request: Request, *, errors=None, invoice_no="", sold_at=None,
                        form_items=None, request_key="", status=200):
    return templates.TemplateResponse(request, "sale_form.html", {
        "active": "transactions", "title": "Buat Transaksi", "errors": errors or [],
        "invoice_no": invoice_no, "sold_at": sold_at or date.today().isoformat(),
        "today_date": date.today().isoformat(),
        "form_items": form_items if form_items is not None else [{"product_id": "", "quantity": "1"}],
        "products": sale_product_options(), "request_key": request_key or str(uuid4()),
        "demo_mode": not (database_path().parent / ".start_empty").exists(),
    }, status_code=status)


@app.get("/transactions/new", response_class=HTMLResponse)
def new_sale_page(request: Request):
    return manual_sale_context(request)


@app.post("/transactions/new", response_class=HTMLResponse, dependencies=[Depends(csrf_guard)])
def submit_sale(request: Request, invoice_no: str = Form(""), sold_at: str = Form(""),
                product_id: list[str] = Form([]), quantity: list[str] = Form([]),
                request_key: str = Form("")):
    try:
        saved = create_sale(invoice_no, sold_at, product_id, quantity, request_key,
                            actor_id=request.state.user['id'])
        return RedirectResponse(url=f"/transactions/{saved['transaction_id']}?success=" +
                                quote("Transaksi berhasil disimpan." if not saved["replayed"] else "Transaksi sebelumnya sudah tersimpan; tidak dibuat dua kali."),
                                status_code=303)
    except DataValidationError as exc:
        items = [{"product_id": pid, "quantity": qty}
                 for pid, qty in zip(product_id[:20], quantity[:20])]
        return manual_sale_context(request, errors=exc.errors, invoice_no=invoice_no, sold_at=sold_at,
                                   form_items=items or [{"product_id": "", "quantity": "1"}],
                                   request_key=request_key, status=422)


@app.get("/transactions/{transaction_id}", response_class=HTMLResponse)
def sale_detail_page(request: Request, transaction_id: int, success: str = ""):
    details = transaction_detail(transaction_id)
    if details is None:
        return Response("Transaksi tidak ditemukan.", status_code=404)
    return page(request, "sale_detail.html", active="transactions", title="Detail Transaksi",
                details=details, success=success)


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request, success: str = ""):
    with connection() as db:
        products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        transactions_count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    return page(request, "imports.html", active="imports", title="Impor Data", success=success,
                errors=[], products_count=products_count, transactions_count=transactions_count)


def upload_result(request, errors, status=422):
    with connection() as db:
        p_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        t_count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    return templates.TemplateResponse(request, "imports.html",
        {"active": "imports", "title": "Impor Data", "errors": errors,
         "success": "", "products_count": p_count, "transactions_count": t_count,
         "demo_mode": not (database_path().parent / ".start_empty").exists()}, status_code=status)


async def file_bytes(upload: UploadFile):
    if not upload.filename or not upload.filename.lower().endswith(".csv"):
        raise DataValidationError(["Pilih file dengan ekstensi .csv."])
    content = await upload.read(2 * 1024 * 1024 + 1)
    return content


@app.post("/imports/products", response_class=HTMLResponse, dependencies=[Depends(csrf_guard)])
async def upload_products(request: Request, file: UploadFile = File(...)):
    try:
        result = import_products(await file_bytes(file), actor_id=request.state.user['id'])
        text = f"Produk berhasil diproses: {result['created']} baru, {result['updated']} diperbarui. Stok awal hanya diterapkan pada produk baru."
        return RedirectResponse(url="/imports?success=" + quote(text), status_code=303)
    except DataValidationError as err:
        return upload_result(request, err.errors)


@app.post("/imports/sales", response_class=HTMLResponse, dependencies=[Depends(csrf_guard)])
async def upload_sales(request: Request, file: UploadFile = File(...)):
    try:
        result = import_sales(await file_bytes(file), actor_id=request.state.user['id'])
        text = f"Berhasil mengimpor {result['transactions']} transaksi dan {result['items']} rincian penjualan. Stok otomatis berkurang."
        return RedirectResponse(url="/imports?success=" + quote(text), status_code=303)
    except DataValidationError as err:
        return upload_result(request, err.errors)


@app.get("/samples/{kind}")
def sample_download(kind: str):
    candidates = {"products": DATA_PATH / "sample_products.csv", "sales": DATA_PATH / "sample_sales.csv"}
    if kind not in candidates:
        return Response(content="Not found", status_code=404)
    return FileResponse(candidates[kind], media_type="text/csv", filename=candidates[kind].name)


def date_filter(from_date: str, to_date: str):
    try:
        start = date.fromisoformat(from_date) if from_date else None
        end = date.fromisoformat(to_date) if to_date else None
    except ValueError:
        raise DataValidationError(["Format tanggal harus YYYY-MM-DD."])
    if start and end and start > end:
        raise DataValidationError(["Tanggal awal tidak boleh lebih besar dari tanggal akhir."])
    return (start.isoformat() if start else None, end.isoformat() if end else None)


@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request, from_date: str = Query("", alias="from"), to_date: str = Query("", alias="to")):
    from_date = from_date or (date.today() - timedelta(days=89)).isoformat()
    to_date = to_date or date.today().isoformat()
    error = ""
    try:
        start, end = date_filter(from_date, to_date)
        lines = report_lines(start, end)
    except DataValidationError as exc:
        error, lines = "; ".join(exc.errors), []
    return page(request, "reports.html", active="reports", title="Laporan",
                from_date=from_date, to_date=to_date, line_count=len(lines),
                transaction_count=len({r['transaction_id'] for r in lines}),
                revenue=sum(r["line_total"] for r in lines),
                units=sum(r["quantity"] for r in lines),
                slow=analyze_inventory(30, classification='slow')['rows'][:8], error=error)


@app.get("/reports/export")
def export_report(from_date: str = Query("", alias="from"), to_date: str = Query("", alias="to"), format: str = "csv"):
    try:
        start, end = date_filter(from_date, to_date)
    except DataValidationError as exc:
        return Response(content="; ".join(exc.errors), media_type="text/plain", status_code=400)
    if format == "csv":
        return Response(content=sales_csv(start, end), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="usahainsight_penjualan.csv"',
                                 "X-Content-Type-Options": "nosniff"})
    if format == "xlsx":
        return Response(content=sales_xlsx(start, end),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="usahainsight_laporan.xlsx"',
                                 "X-Content-Type-Options": "nosniff"})
    return Response(content="Format tidak dikenal. Pilih csv atau xlsx.", status_code=400)


@app.get('/audit', response_class=HTMLResponse)
def audit_page(request: Request, action: str = '', q: str = '', p: int = 1):
    records = list_events(action=action, query=q, page=p)
    return page(request, 'audit.html', active='audit', title='Audit Trail',
                data=records, action=action if action in ACTIONS else '', q=q[:90],
                actions=sorted(ACTIONS))


@app.get('/insights', response_class=HTMLResponse)
def inventory_insights(request: Request, days: int = 30, q: str = '', category: str = '', status: str = 'all'):
    if days not in WINDOWS:
        days = 30
    if status not in FILTERS:
        status = 'all'
    result = analyze_inventory(days, q=q, category=category, classification=status)
    return page(request, 'insights.html', active='insights', title='Analitik Persediaan', data=result)


@app.get('/insights/export')
def export_inventory_insights(days: int = 30, q: str = '', category: str = '',
                              status: str = 'all', format: str = 'xlsx'):
    if days not in WINDOWS or status not in FILTERS:
        return Response('Filter periode atau klasifikasi tidak valid.', status_code=400)
    result = analyze_inventory(days, q=q, category=category, classification=status)
    if format == 'csv':
        return Response(intelligence_csv(result), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="usahainsight_analitik.csv"',
                                 'X-Content-Type-Options': 'nosniff'})
    if format == 'xlsx':
        return Response(intelligence_xlsx(result),
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="usahainsight_analitik.xlsx"',
                                 'X-Content-Type-Options': 'nosniff'})
    return Response('Format hanya csv atau xlsx.', status_code=400)



@app.get('/restock-planner', response_class=HTMLResponse)
def restock_planner_page(request: Request, days: int = 30, q: str = '',
                         category: str = '', status: str = 'all', success: str = '', error: str = ''):
    if days not in WINDOWS:
        days=30
    if status not in STATUSES:
        status='all'
    result=restock_recommendations(days,q=q,category=category,status=status)
    return page(request, 'restock_planner.html', active='restock-planner',
                title='Rekomendasi Restock', data=result, success=success, error=error)


@app.post('/restock-planner/{product_id}/settings', dependencies=[Depends(csrf_guard)])
def update_restock_settings(request: Request, product_id: int,
                            lead_time_days: str = Form(''), safety_stock_units: str = Form(''),
                            review_days: str = Form('')):
    try:
        changed=save_reorder_settings(product_id,lead_time_days,safety_stock_units,review_days,
                                      actor_id=request.state.user['id'])
    except ValueError as exc:
        return RedirectResponse('/restock-planner?error='+quote(str(exc)), status_code=303)
    msg='Parameter berhasil disimpan.' if changed else 'Parameter tidak berubah.'
    return RedirectResponse('/restock-planner?success='+quote(msg), status_code=303)


@app.get('/restock-planner/export')
def export_restock_planner(days: int = 30, q: str = '', category: str = '',
                           status: str = 'all', format: str = 'xlsx'):
    if days not in WINDOWS or status not in STATUSES:
        return Response('Filter tidak valid.', status_code=400)
    result=restock_recommendations(days,q=q,category=category,status=status)
    if format == 'csv':
        return Response(restock_csv(result), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="usahainsight_restock.csv"',
                                 'X-Content-Type-Options': 'nosniff'})
    if format == 'xlsx':
        return Response(restock_xlsx(result),
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="usahainsight_restock.xlsx"',
                                 'X-Content-Type-Options': 'nosniff'})
    return Response('Format hanya csv atau xlsx.', status_code=400)


@app.get("/health")
def health():
    return {"status": "ok", "service": "UsahaInsight", "version": "1.4b.0"}
