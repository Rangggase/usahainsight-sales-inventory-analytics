"""Business queries: revenue derives from sale-time line totals; stock derives from ledger."""
from collections import defaultdict
from datetime import date, timedelta
from math import ceil

from app.database import connection


def period_start(period: str):
    if period in ("7", "30", "90"):
        return (date.today() - timedelta(days=int(period) - 1)).isoformat()
    return None


def inventory_rows(q="", limit=None):
    with connection() as db:
        sql = """SELECT *, CASE WHEN current_stock = 0 THEN 'Habis'
                              WHEN current_stock <= min_stock THEN 'Menipis'
                              ELSE 'Aman' END AS status
                 FROM product_inventory WHERE id IN (SELECT id FROM products WHERE is_active=1) AND (sku LIKE ? OR name LIKE ? OR category LIKE ?)
                 ORDER BY CASE WHEN current_stock = 0 THEN 0 WHEN current_stock <= min_stock THEN 1 ELSE 2 END,
                          current_stock ASC, name COLLATE NOCASE"""
        pattern = "%" + q.strip()[:100] + "%"
        if limit is not None:
            sql += " LIMIT ?"
            return [dict(r) for r in db.execute(sql, (pattern, pattern, pattern, limit))]
        return [dict(r) for r in db.execute(sql, (pattern, pattern, pattern))]


def dashboard(period="all"):
    start = period_start(period)
    predicate = "WHERE t.sold_at >= ?" if start else ""
    params = (start,) if start else ()
    with connection() as db:
        kpi = dict(db.execute(f"""SELECT COALESCE(SUM(i.line_total),0) AS revenue,
                    COALESCE(SUM(i.quantity),0) AS units,
                    COUNT(DISTINCT t.id) AS transactions
                    FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id {predicate}""", params).fetchone())
        inventory = dict(db.execute("""SELECT COUNT(*) AS product_count,
                      COALESCE(SUM(CASE WHEN current_stock <= min_stock THEN 1 ELSE 0 END),0) AS low_stock,
                      COALESCE(SUM(CASE WHEN current_stock = 0 THEN 1 ELSE 0 END),0) AS out_of_stock,
                      COALESCE(SUM(current_stock),0) AS units_in_stock FROM product_inventory WHERE id IN (SELECT id FROM products WHERE is_active=1)""").fetchone())
        top = [dict(r) for r in db.execute(f"""SELECT p.name, p.sku, SUM(i.quantity) AS units,
                     SUM(i.line_total) AS revenue
                     FROM transaction_items i JOIN transactions t ON t.id=i.transaction_id
                     JOIN products p ON p.id=i.product_id {predicate}
                     GROUP BY p.id ORDER BY units DESC, revenue DESC LIMIT 6""", params)]
        recent = [dict(r) for r in db.execute(f"""SELECT t.invoice_no, t.sold_at,
                          SUM(i.line_total) AS total, SUM(i.quantity) AS quantity
                          FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id {predicate}
                          GROUP BY t.id ORDER BY t.sold_at DESC, t.id DESC LIMIT 6""", params)]
        recent_all = [dict(r) for r in db.execute("""SELECT t.sold_at, SUM(i.line_total) AS revenue
                  FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id
                  GROUP BY t.sold_at ORDER BY t.sold_at""")]
    latest = date.fromisoformat(recent_all[-1]["sold_at"]) if recent_all else date.today()
    end_of_week = latest + timedelta(days=6 - latest.weekday())
    week_starts = [end_of_week - timedelta(days=6 + 7*i) for i in reversed(range(10))]
    revenue_by_week = defaultdict(int)
    for r in recent_all:
        sale_day = date.fromisoformat(r["sold_at"])
        if start and sale_day < date.fromisoformat(start):
            continue
        week_monday = sale_day - timedelta(days=sale_day.weekday())
        revenue_by_week[week_monday] += r["revenue"]
    trend = [{"label": d.strftime("%d/%m"), "value": revenue_by_week[d]} for d in week_starts]
    chart = chart_svg_data(trend)
    max_units = max((p["units"] for p in top), default=1)
    for p in top:
        p["percent"] = max(4, round(p["units"] / max_units * 100))
    return {**kpi, **inventory, "top": top, "recent": recent,
            "low_products": [p for p in inventory_rows(limit=5) if p["current_stock"] <= p["min_stock"]],
            "chart": chart, "period": period}


def chart_svg_data(points):
    left, top, width, bottom = 55, 18, 790, 198
    peak = max((p["value"] for p in points), default=0)
    max_y = max(100000, ceil(peak / 100000) * 100000)
    xy = []
    for i, p in enumerate(points):
        x = left + (width / max(len(points)-1, 1)) * i
        y = bottom - (p["value"] / max_y) * (bottom-top)
        xy.append({"x": round(x, 2), "y": round(y, 2), **p})
    line = " ".join(("M" if i == 0 else "L") + f"{p['x']} {p['y']}" for i,p in enumerate(xy))
    area = line + f" L{xy[-1]['x']} {bottom} L{xy[0]['x']} {bottom} Z" if xy else ""
    ticks = [{"y": bottom - ((bottom-top)/4)*i,
              "value": round(max_y / 4 * i)} for i in range(5)]
    return {"points": xy, "line": line, "area": area, "ticks": ticks}


def transactions_list(q="", limit=150):
    pattern = "%" + q.strip()[:100] + "%"
    with connection() as db:
        return [dict(r) for r in db.execute("""SELECT t.id, t.invoice_no, t.sold_at,
                  SUM(i.line_total) AS total, SUM(i.quantity) AS units, COUNT(i.id) AS item_count
                  FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id
                  WHERE t.invoice_no LIKE ?
                  GROUP BY t.id ORDER BY t.sold_at DESC, t.id DESC LIMIT ?""", (pattern,limit))]


def report_lines(start=None, end=None):
    with connection() as db:
        return [dict(r) for r in db.execute("""SELECT t.invoice_no AS transaction_id, t.sold_at AS date,
                p.sku, p.name AS product, p.category, i.quantity, i.unit_price, i.line_total
                FROM transaction_items i JOIN transactions t ON t.id=i.transaction_id
                JOIN products p ON p.id=i.product_id
                WHERE (? IS NULL OR t.sold_at >= ?) AND (? IS NULL OR t.sold_at <= ?)
                ORDER BY t.sold_at DESC, t.invoice_no DESC, p.sku""", (start,start,end,end))]


def slow_moving(days=30):
    cutoff = (date.today() - timedelta(days=days-1)).isoformat()
    with connection() as db:
        return [dict(r) for r in db.execute("""SELECT p.name, p.sku, inv.current_stock,
                COALESCE(SUM(CASE WHEN t.sold_at >= ? THEN i.quantity ELSE 0 END),0) AS units_sold
                FROM products p JOIN product_inventory inv ON inv.id=p.id
                LEFT JOIN transaction_items i ON i.product_id=p.id
                LEFT JOIN transactions t ON t.id=i.transaction_id
                WHERE p.is_active=1 GROUP BY p.id HAVING units_sold <= 2
                ORDER BY units_sold, inv.current_stock DESC LIMIT 8""", (cutoff,))]
