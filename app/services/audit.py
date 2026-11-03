"""Audit of authenticated web business changes, atomic with original writes."""
import json
from app.database import connection

ACTIONS = {
    'product.created', 'product.updated', 'product.archived', 'product.restored',
    'stock.restocked', 'sale.created', 'products.imported', 'sales.imported',
    'reorder.settings_updated',
}


def write_audit(db, actor_id, action, target_type, target_id=None, *, before=None, after=None, summary=''):
    """Caller owns the transaction. No event for seed/CLI operations (actor_id=None)."""
    if actor_id is None:
        return
    if action not in ACTIONS or target_type not in {'product', 'stock_movement', 'transaction', 'import'}:
        raise ValueError('Aksi atau target audit tidak dikenal.')
    actor = db.execute('SELECT id,username FROM auth_users WHERE id=?', (actor_id,)).fetchone()
    if not actor:
        raise ValueError('Pengguna audit tidak ditemukan.')
    db.execute("""INSERT INTO audit_events(actor_user_id,actor_username,action,target_type,
                   target_id,before_json,after_json,summary) VALUES (?,?,?,?,?,?,?,?)""",
       (actor['id'], actor['username'], action, target_type, target_id,
        json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
        json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
        summary[:250]))


def list_events(*, action='', query='', page=1, per_page=25):
    """Read-only, parameterized paginated browsing."""
    if action not in ACTIONS:
        action = ''
    page = max(1, min(int(page), 1000000))
    per_page = max(1, min(int(per_page), 100))
    query = (query or '').strip()[:90]
    conditions, args = ['1=1'], []
    if action:
        conditions.append('action=?')
        args.append(action)
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        conditions.append("(actor_username LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\')")
        args.extend(['%'+escaped+'%']*3)
    predicate = ' AND '.join(conditions)
    with connection() as db:
        total = db.execute('SELECT COUNT(*) FROM audit_events WHERE '+predicate, args).fetchone()[0]
        result = [dict(r) for r in db.execute("""SELECT id,actor_username,action,target_type,
             target_id,summary,before_json,after_json,created_at FROM audit_events WHERE """
             +predicate+" ORDER BY id DESC LIMIT ? OFFSET ?",args+[per_page, (page-1)*per_page])]
    for event in result:
        old, new = event.pop('before_json'),event.pop('after_json')
        event['before'] = json.loads(old) if old is not None else None
        event['after'] = json.loads(new) if new is not None else None
    return {'events':result,'total':total,'page':page,'per_page':per_page,
            'pages':max(1,(total+per_page-1)//per_page)}
