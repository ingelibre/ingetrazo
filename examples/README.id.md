# Contoh proyek

Bahasa Indonesia · [Español](README.md)

Empat dokumen ini dibuat oleh Marco Sumari Tellez dengan IngeTrazo untuk
proyek penataan alun-alun Yanque di Distrik Chichas, Arequipa, pada 2026.
Buka melalui **Berkas ▸ Buka** atau klik dua kali jika IngeTrazo sudah
terpasang. Tiga dokumen dilengkapi lembar A3 yang siap dibuka melalui
**Berkas ▸ Penyusun lembar**. PDF hasil ekspornya tersedia di folder yang
sama untuk dibandingkan.

| Berkas | Isi | Fitur yang dapat dipelajari |
|---|---|---|
| `pileta-fuente-yanque.igz` (+ `.pdf`) | Air mancur pusat alun-alun: alas segi delapan, tiang beralur, dua mangkuk bertepi bergelombang, dan trotoar dengan tepi membulat | Komponen berulang (22 instans), bayangan sesuai posisi matahari, bidang potong, serta lembar berisi denah, potongan, dan detail |
| `banca-pergola-yanque.igz` (+ `.pdf`) | Bangku beton dengan pergola kayu | Komponen, lima scene tersimpan, serta lembar dengan 23 dimensi dan 12 label bergaris penunjuk |
| `luminaria-solar-yanque.igz` (+ `.pdf`) | Tiang lampu tenaga surya setinggi 4,5 m: pedestal berbentuk kerucut terpancung, fondasi tertanam dengan tulangan 3/8 inci, dua lampu sorot, dan panel surya | Pemodelan melalui Asisten AI dan jembatan MCP, detail tulangan, serta lembar dengan empat tampilan |
| `arco-yanque.igz` | Gapura «YANQUE» sesuai gambar struktur E02: beton, seluruh tulangan fondasi tapak, kolom, busur segmental, balok dan bidang pengisi, kepala kolom dari batu sillar, empat lampu hias, huruf, dan patung | Sinar-X untuk melihat tulangan, bidang potong, gambar yang selalu menghadap kamera, dan tekstur |

Dokumen disimpan dengan versi 0.3.12 atau lebih baru dan tidak dapat dibuka
oleh versi sebelumnya. Ukuran keempatnya sekitar 6,3 MB.

## Layer

`capas-prueba.igz` adalah dokumen latihan untuk mencoba seluruh fitur layer:
folder bersarang, layer aktif, sepuluh jenis garis, ketebalan garis,
transparansi, layer terkunci, layer yang tidak dicetak, layer kosong untuk
dibersihkan, scene, dan lembar dengan legenda. Dokumen ini dipakai dalam
[panduan layer](../docs/layers.id.md) beserta tangkapan layarnya.

Untuk membuat ulang dokumen setelah mencoba mengubahnya, jalankan dari
folder utama IngeTrazo:

```bash
python examples/capas-prueba.py
```

## Tab, scene, dan tampilan

`pestanas-prueba.igz` berisi rumah sederhana dengan empat scene: Exterior
(eksterior), Planta (denah), Alzado (tampak depan), dan Lateral (tampak
samping). Scene muncul sebagai tab di bawah area model. Gunakan dokumen ini
untuk mencoba susunan beberapa tampilan, seperti dijelaskan dalam
[panduan tab proyek](../docs/project-tabs.id.md).

Untuk membuat ulang dokumen, jalankan dari folder utama IngeTrazo:

```bash
python examples/pestanas-prueba.py
```

## Ekstensi

`extensions/niveles.py`, bernama **Niveles**, menyimpan elevasi lantai
bangunan (PB, PA, dan seterusnya) di dalam dokumen. Ekstensi menampilkan
garis bantu putus-putus pada tampak dan potongan dengan proyeksi paralel,
serta menyediakan snap kursor pada elevasi tersebut. Gagasan dan versi
pertamanya dibuat oleh José Castro Basso (FADU–UDELAR).

Ekstensi disertakan dalam IngeTrazo tetapi belum diaktifkan. Pasang melalui
**Ekstensi ▸ Kelola ekstensi…** atau salin ke folder plugin, lalu mulai
ulang IngeTrazo. Tab «Niveles» akan muncul pada panel samping.

## Lisensi

Dokumen dalam folder ini, termasuk model, lembar, dan PDF, adalah karya
Marco Sumari Tellez yang diterbitkan dengan lisensi
[Creative Commons Atribusi 4.0](https://creativecommons.org/licenses/by/4.0/deed.id).
Anda boleh menggunakan, mengubah, dan membagikannya dengan mencantumkan
sumber. Kode IngeTrazo tetap memakai lisensi GPL-3.0-or-later repositori.
