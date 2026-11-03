# Entity Relationship Diagram — UsahaInsight

```mermaid
erDiagram
    PRODUCTS ||--o{ TRANSACTION_ITEMS : "dibeli"
    TRANSACTIONS ||--|{ TRANSACTION_ITEMS : "berisi"
    PRODUCTS ||--o{ STOCK_MOVEMENTS : "memiliki"
    TRANSACTIONS |o--o{ STOCK_MOVEMENTS : "terkait penjualan"
    PRODUCTS {
        int id PK
        string sku UK
        string name
        string category
        int unit_price
        int min_stock
    }
    TRANSACTIONS {
        int id PK
        string invoice_no UK
        date sold_at
    }
    TRANSACTION_ITEMS {
        int id PK
        int transaction_id FK
        int product_id FK
        int quantity
        int unit_price
        int line_total
    }
    STOCK_MOVEMENTS {
        int id PK
        int product_id FK
        int transaction_id FK "nullable"
        string movement_type
        int delta
        string note
    }
```

## Peraturan penting

- Omzet = total `transaction_items.line_total` pada tanggal transaksi yang dipilih.
- Harga penjualan disimpan per item transaksi; perubahan harga master produk **tidak** mengubah omzet historis.
- Stok saat ini = penjumlahan seluruh `stock_movements.delta` per produk melalui view `product_inventory`.
- `initial` dan `restock` menambah stok; `sale` mengurangi stok; stok tidak boleh menjadi negatif.
- Impor produk dengan SKU yang sudah ada memperbarui katalog, tetapi **tidak** menambahkan ulang stok awal.
- `invoice_no` unik, serta `(transaction_id, product_id)` unik untuk detail; impor ulang invoice dibatalkan.
- Seluruh impor per file bersifat atomik: satu kesalahan membatalkan semua perubahan pada file itu.
- Aplikasi ini dirancang untuk **single-store, local demo**, tanpa autentikasi. Jangan deploy terbuka ke internet tanpa kontrol keamanan dan hak akses.


## v1.2 — Idempotensi transaksi manual

`manual_sale_requests(request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id))` mencatat kunci satu-kali per formulir. Tabel ini **tidak mengganti** `transactions` atau `transaction_items` dan dibuat saat `init_db()` pertama setelah upgrade. Pengiriman ulang kunci dan payload yang sama mengembalikan ID transaksi lama, tidak mengurangi stok lagi. Kunci sama dengan payload berbeda ditolak.
