# Berkontribusi pada IngeTrazo

Bahasa Indonesia · [English](CONTRIBUTING.md)

Kontribusi dalam bentuk apa pun dipersilakan: kode, dokumentasi, terjemahan,
laporan bug, atau masukan desain.

## Menyiapkan lingkungan pengembangan

Buat fork repositori, lalu jalankan:

```bash
git clone https://github.com/<your-user>/ingetrazo.git
cd ingetrazo
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Gunakan Python 3.12 atau lebih baru. Di Windows dengan PowerShell,
buat lingkungan virtual menggunakan `python -m venv venv`, lalu aktifkan
dengan `.\venv\Scripts\Activate.ps1` sebagai pengganti perintah `source`.

## Pengujian dan CI

```bash
python -m pytest -m "not slow"
python -m pytest
```

Perintah pertama menjalankan pengujian cepat. Perintah kedua menjalankan
semua pengujian, termasuk pengujian fuzz yang lebih lama. Untuk menjalankan
pengujian cepat per kelompok seperti di CI, gunakan:

```bash
python scripts/pytest_batches.py -m "not slow" tests
```

Setiap pull request menjalankan pengujian cepat secara otomatis. Hasilnya
ditandai centang hijau atau silang merah, tanpa perlu menunggu pengelola
menjalankannya. Fitur baru perlu disertai pengujian. Perbaikan bug perlu
pengujian regresi yang gagal sebelum perbaikan diterapkan.

## Gaya kode

- Tulis kode, komentar, pesan commit, dan deskripsi pull request dalam
  **bahasa Inggris** agar kontributor dari berbagai negara dapat memahaminya.
- Ikuti PEP 8 dengan batas lunak 100 karakter per baris.
- Gunakan anotasi tipe untuk API publik jika memungkinkan.
- Tulis docstring yang singkat dan jelas untuk API publik.
- Jangan menulis teks antarmuka secara langsung tanpa sistem terjemahan.
  Teks sumber berbahasa Inggris menjadi kunci pemanggilan `tr()`. Terjemahan
  Spanyol berada di `i18n/es.json`, dan Indonesia di `i18n/id.json`.
  Bahasa Inggris memakai teks sumber; `i18n/en.json` sengaja kosong.

## Susunan folder

[docs/architecture.md](docs/architecture.md) menjelaskan arsitektur proyek
lebih lanjut. Gambaran singkatnya:

- `core/`: mesin geometri, mesh dengan vertex bersama, scene, kamera, snap,
  topologi, riwayat perubahan (`Command`), tag BIM, terjemahan, dan pencarian plugin.
- `views/`: widget Qt, termasuk jendela utama, area model, dan panel samping.
- `tools/`: alat pemodelan bawaan seperti garis, persegi panjang, dorong/tarik, dan pilih.
- `plugins/`: plugin yang ditemukan saat aplikasi berjalan. Info Model dan
  Konsol Python bawaan juga menjadi contoh implementasi.
- `georef/`: lokasi dunia nyata, datum, ubin peta, medan DEM, jalur geografis,
  titik survei, dan mesh fotogrametri.
- `formats/`: impor/ekspor `.igz`, `.skp`, OBJ, COLLADA, glTF/GLB, STL, dan IFC.
- `i18n/`: terjemahan antarmuka dalam berkas JSON per bahasa, dengan teks Inggris sebagai kunci.
- `resources/`: shader, ikon, tekstur, dan komponen.
- `scripts/`: alat bantu pengembangan dan contoh skrip konsol.
- `docs/`: dokumentasi arsitektur dan kontribusi.
- `tests/`: pengujian otomatis dengan pytest.

## Memperbaiki terjemahan Indonesia

Edit nilai dalam [`i18n/id.json`](i18n/id.json), tanpa mengubah kunci
berbahasa Inggris. Pertahankan placeholder seperti `{name}`, `{n}`, dan
`{mb:.1f}`, spasi di awal atau akhir teks, tag HTML, nama berkas, serta
perintah yang perlu diketik pengguna.

Gunakan bahasa yang jelas dan wajar dibaca. Untuk istilah CAD, ikuti nama
yang sudah dipakai antarmuka: **bidang**, **tepi**, **titik sudut**,
**layer**, **scene**, dan **Penyusun lembar**. Gunakan **kuantitas** jika
datanya mencakup luas, panjang, jumlah, atau volume, bukan hanya volume.

Jalankan pemeriksaan katalog setelah mengedit:

```bash
python -m pytest -q tests/test_translation_files.py
```

Dokumentasi Indonesia memakai akhiran `.id.md`, misalnya `README.id.md`.
Tautkan versi terjemahan dari dokumen sumber dan sertakan tautan kembali
agar pembaca dapat memeriksa informasi terbaru.

## Membuat plugin

Plugin menjadi cara mudah menambah fitur tanpa membuat fork. Letakkan
berkas Python di folder plugin pengguna; alatnya akan muncul di menu
**Ekstensi**. Untuk mencoba langsung pada dokumen aktif, buka
**Ekstensi → Konsol Python** (`Ctrl+Shift+P`). Setiap eksekusi menjadi satu
langkah yang dapat diurungkan.

[docs/plugins.md](docs/plugins.md) menjelaskan aturan penemuan plugin,
penanganan kegagalan, dan pola `SnapshotImport` untuk mengubah model.
API plugin **belum stabil** pada versi 0.x. Plugin yang diterbitkan
sekarang mungkin perlu diperbarui saat versi minor berubah.

## Alur kontribusi

1. Buat **fork** repositori.
2. Buat branch fitur: `git checkout -b feature/short-description`.
3. Buat commit kecil dengan fokus jelas dan pesan yang menjelaskan perubahan.
4. Jalankan pengujian cepat di komputer Anda.
5. Push branch ke fork, lalu buka **pull request**. CI akan menjalankan
   pengujian secara otomatis.
6. Tunggu tinjauan pengelola. Tim berusaha merespons dalam waktu satu minggu.

## Melaporkan masalah

- **Laporan bug:** jelaskan masalah, langkah untuk mengulanginya, hasil yang
  diharapkan dan yang terjadi, serta tangkapan layar jika membantu.
- **Permintaan fitur:** jelaskan kebutuhan, manfaatnya, dan alat lain yang
  sudah menyediakan fungsi serupa.
- **Good first issue:** issue dengan label ini cocok untuk kontributor baru.
  Beri komentar pada issue jika ingin mengerjakannya.

## Komunikasi

Gunakan **issue** untuk bug dan usulan fitur. Gunakan **GitHub Discussions**
untuk pertanyaan terbuka, pembahasan arsitektur, atau berbagi proyek yang
dibuat dengan IngeTrazo.

## Lisensi kontribusi

Dengan mengirimkan kontribusi, Anda menyetujui bahwa kontribusi tersebut
dilisensikan di bawah **GPL-3.0-or-later**, sesuai lisensi proyek.
