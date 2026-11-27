# Futbol Analiz Botu — ilk prototip

Python 3.10+ gerekir. PostgreSQL kullanıldığında `pip install -r requirements.txt` çalıştırın.

## Başlatma

Terminalde bu klasörde:

```bash
python app.py
```

Tarayıcı: http://localhost:8080

Anahtar girilmezse yalnızca **örnek maç** gösterilir; hiçbir sayı gerçek analiz olarak sunulmaz.

## Gerçek veri

[football-data.org](https://www.football-data.org/) üzerinden bir API anahtarı alın. Windows PowerShell örneği:

```powershell
$env:FOOTBALL_DATA_TOKEN="API_ANAHTARINIZ"
$env:TELEGRAM_BOT_TOKEN="BOTFATHER_BOT_TOKEN"
$env:TELEGRAM_CHAT_ID="HEDEF_CHAT_ID"
python app.py
```

Telegram için BotFather üzerinden bot açın; botu hedef sohbetinize ekleyin ve chat ID belirleyin. **Tokenları kimseyle paylaşmayın.**

## Mevcut durum ve sınırlar

- Maç listesi, son beş tamamlanmış maçın gol istatistiği, kontrol paneli, hata kaydı ve manuel Telegram gönderimi prototipte vardır.
- API sağlayıcısının desteklediği maçlarla sınırlıdır; **tüm dünya ligleri garantisi yoktur**.
- İkili rekabet, lig sıralaması, ilk yarı oranları, bütçeler, eksikler, teknik direktör ve geçmiş bahis oranları için henüz doğrulanmış sağlayıcı entegrasyonu yoktur. Bu alanlar `null` olarak işaretlenir.
- Eksik analizler 'başarılı' sayılmaz. Tamamlanan sayısı ancak tüm zorunlu başlıklar doğrulanırsa artacaktır.
- Telegram gönderimi manuel tetiklenir. Otomatik bildirim, sunucuya kurulum ve sürekli çalışma henüz yapılmamıştır.
- Testler için önce küçük lig örnekleriyle API kapsama alanı ve rate limit kontrol edilmelidir.
- Bot yerel `127.0.0.1` üzerinde dinler; internetten erişilebilir bir web sitesi değildir.

## Üyelik kilidi

Varsayılan mod mevcut erişimi korur. Yerel deneme için `MEMBERSHIP_MODE=local` seçin.
Bu mod yalnızca localhost'a bağlanır. İlk yönetici hesabı sunucu açılırken oluşturulur.

| Ortam değişkeni | Değer |
| --- | --- |
| `MEMBERSHIP_MODE` | Yerelde `local`, HTTPS ile canlı ortamda `on` |
| `MEMBERSHIP_DATABASE_URL` | Canlı PostgreSQL bağlantı adresi, gizli değişken |
| `MEMBERSHIP_DB_PATH` | PostgreSQL adresi verilmediğinde  Yerelde geçici bir SQLite yolu, canlıda kalıcı diskin doğrudan altında mutlak SQLite dosya yolu |
| `MEMBERSHIP_ADMIN_PHONE` | İlk yöneticinin telefon numarası |
| `MEMBERSHIP_ADMIN_PASSWORD` | İlk yöneticinin en az 12 karakterlik şifresi |

Yönetici bilgilerini barındırma ortamının gizli değişkenleri olarak ekleyin.
Önceden oluşturulmuş yönetici hesabının şifresi ortam değişkeniyle değişmez.
Canlı modda HTTPS ile PostgreSQL veya kalıcı SQLite depolaması kullanılır.
Render Free için PostgreSQL kullanın ve Render derleme komutunda
`pip install -r requirements.txt` çalıştırın. PostgreSQL bağlantısı sunucu
sertifikasını ve alan adını doğrular.
Render sağlık kontrolü için `/healthz` yolunu kullanın.

Ziyaretçi giriş ekranından üyelik başvurusu yapar. Yönetici giriş yaptıktan
sonra **Üyeleri yönet** ekranından başvuruyu onaylar, erişimi açar veya
engeller. Engelleme mevcut oturumları da kapatır. Üyelik açıkken maç,
analiz ve Telegram uçları geçerli oturum ister.

### Ek geçmiş maç verisi

[open-matchday](https://github.com/oladeeayo/open-matchday) 2026/27 sonuçları, kapsanan liglerde geçmiş maç ve doğrulanabilir devre skoru yedeği olarak kullanılır. Kaynak, ticari olmayan kullanım içindir.
