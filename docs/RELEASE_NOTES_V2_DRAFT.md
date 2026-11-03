# UsahaInsight v2.0.0 — Portfolio Release (DRAFT)

> Draft. Jangan publikasikan sebelum audit keamanan dan UAT selesai. Ini demonstrasi lokal untuk portofolio, **bukan layanan produksi**.

## Highlights
- Product management, validasi impor CSV, transaksi penjualan multi-produk, inventaris, dan laporan.
- Dashboard penjualan, slow-moving analysis, sales velocity, serta stock coverage.
- Smart restock berbasis lead time, safety stock, dan review period dengan alasan yang dapat diperiksa.
- Login administrator, sesi, pencatatan audit, serta backup/restore SQLite.
- Diagram ERD, arsitektur sistem, proses bisnis, screenshot, dan petunjuk instalasi.

## Verification (reported by project developer)
- 114/114 automated tests passed on fresh clone.
- 7/7 clean installation scenarios passed.
- 8/8 v1.4b manual acceptance tests passed.

## Limitations
- Aplikasi lokal untuk demonstrasi satu administrator, bukan production service publik.
- Evaluasi keamanan lebih lanjut diperlukan sebelum pemakaian nyata atau deployment internet.
- Saran pembelian berbasis rumus deterministik, bukan prediksi permintaan terjamin.
- Dataset publik yang disertakan harus sintetis atau sudah mendapat izin.

## Publish gate
- [ ] Audit konten dan Git history tuntas.
- [ ] UAT pengguna UMKM dilakukan dan hasilnya didokumentasikan.
- [ ] README dan video demo diverifikasi.
- [ ] Perbedaan nomor versi internal aplikasi dan label release dijelaskan.

## Validation Results

- Automated testing: 114 tests passed.
- Clean installation verification: 7 of 7 checks passed.
- Developer acceptance testing: 6 of 6 scenarios passed.
- External MSME user acceptance testing: Not conducted.

## Known Limitations

- The application is intended for local, single-administrator use.
- Usability has not been independently validated with real MSME users.
- Public production deployment requires additional security,
  operational, and deployment review.