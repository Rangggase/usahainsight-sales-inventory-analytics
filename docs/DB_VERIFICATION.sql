-- UsahaInsight v2.0 — perintah pemeriksaan READ-ONLY di PyCharm Pro.
-- Jalankan satu blok per kali. JANGAN kirim nilai password_hash, token_hash, csrf_token,
-- cookie atau file database asli kepada orang lain.

-- 1. Pastikan file yang sedang dibaca (jangan asumsikan nama koneksinya cukup).
PRAGMA database_list;

-- 2. Tampilkan tabel dan view aplikasi. Diharapkan 9 tabel + 1 view pada v1.4b.
SELECT type, name
FROM sqlite_master
WHERE type IN ('table','view')
  AND name NOT LIKE 'sqlite_%'
ORDER BY type, name;

-- 3. Pastikan modul restock v1.4b memiliki tabel konfigurasinya.
SELECT name FROM sqlite_master WHERE type='table' AND name='reorder_settings';

-- 4. Periksa kolom inti dan aturan foreign key (aman / tidak mengubah data).
PRAGMA table_info(products);
PRAGMA table_info(reorder_settings);
PRAGMA foreign_key_list(transaction_items);
PRAGMA foreign_key_list(stock_movements);
PRAGMA foreign_key_list(manual_sale_requests);
PRAGMA foreign_key_list(reorder_settings);
PRAGMA foreign_key_list(auth_sessions);
PRAGMA foreign_key_list(audit_events);

-- 5. Periksa integritas; hasil normal adalah 'ok' dan tidak ada baris FK bermasalah.
PRAGMA integrity_check;
PRAGMA foreign_key_check;

-- 6. Ringkasan jumlah baris TANPA menampilkan akun, hash atau token.
SELECT 'products' AS entity, COUNT(*) AS total FROM products
UNION ALL SELECT 'transactions', COUNT(*) FROM transactions
UNION ALL SELECT 'transaction_items', COUNT(*) FROM transaction_items
UNION ALL SELECT 'stock_movements', COUNT(*) FROM stock_movements
UNION ALL SELECT 'manual_sale_requests', COUNT(*) FROM manual_sale_requests
UNION ALL SELECT 'audit_events', COUNT(*) FROM audit_events
UNION ALL SELECT 'reorder_settings', COUNT(*) FROM reorder_settings
ORDER BY entity;
