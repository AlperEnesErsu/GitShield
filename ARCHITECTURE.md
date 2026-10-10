# GitShield — Mimari ve Tasarım Belgesi

## 1. Giriş ve Amaç

**GitShield**, geliştirme sürecinde (yerel terminal ve CI/PR akışı) kod güvenliğini sürtünmesiz hale getirmeyi amaçlayan bir güvenlik denetim aracıdır.

Geleneksel SAST çözümleri genellikle tüm kod tabanını tarar ve geliştiriciyi çok sayıda yanlış pozitifle boğar. GitShield bu yüzden **yalnızca değişen kodu** inceler ve bulgular için **LLM destekli düzeltme önerisi** üretir. Önerilen kod otomatik uygulanmaz ve test edilmez; geliştirici inceleyerek uygular.

---

## 2. Temel Tasarım İlkeleri

1. **Diff-First (Yalnızca Eklenen Satırlar):** Tarayıcı, `git diff` çıktısındaki eklenen (`+`) satırları tarar. Bağlam satırları (`-U3`) yalnızca ayrıştırma için okunur; bulgu üretilmez. Düzeltme aşamasında ise bulgunun dosyadaki ±8 satırlık bağlamı kullanılır.
2. **Çift Kademeli Tespit (Deterministik + Heuristik):**
   - **Deterministik:** 20 sır kuralı ve 6 OWASP kuralı (satır bazlı regex, dosya uzantısı kapsamıyla).
   - **Heuristik:** Tırnak içindeki rastgele görünümlü değerler için Shannon entropisi (`H(X) = -Σ P(x) log2 P(x)`), uzunluğa bağlı eşikle. Entropi sezgisi yanlış pozitif üretebilir; `--no-entropy` ile kapatılabilir.
3. **AST Analizi Yoktur:** Kurallar satır bazlıdır. Veri akışı, fonksiyon sınırı veya dil ayrıştırması yapılmaz. Bu, kapsamı bilinçli olarak sınırlar; bkz. Bölüm 9.
4. **Fail-Closed Git Hataları:** Git hatası (geçersiz ref, depo olmayan dizin, git yok) boş bir raporla geçilmez; tarama çıkış kodu 2 ile durur.
5. **Açık Standartlar (SARIF 2.1.0):** Sonuçlar GitHub Code Scanning ile uyumlu SARIF olarak dışa aktarılır.
6. **Sır Sızdırmama:** Ham sır değerleri konsola, dosyaya, stdout'a ve LLM'e gitmez (bkz. Bölüm 7).

---

## 3. Katmanlı Mimari Şeması

```
+----------------------------------------------------------------------+
|  Giriş: gitshield scan (cli.py)  |  GitHub Action (action.yml)       |
|  gitshield web  (web/, FastAPI)  |                                    |
+----------------------------------------------------------------------+
                                  |
                                  v
+----------------------------------------------------------------------+
|  Diff Ayrıştırıcı (core/diff_parser.py)                              |
|  - git diff -U3 (HEAD | --cached | --branch REF)                      |
|  - untracked dosyalar: ls-files --others --exclude-standard          |
|  - hunk sayaçlarıyla satır izleme; tırnaklı/escape'li yollar          |
|  - git hatası -> GitDiffError -> çıkış kodu 2                        |
+----------------------------------------------------------------------+
                                  |
                                  v   (yalnızca '+' satırları)
+----------------------------------------------------------------------+
|  Scanner (core/scanner.py)                                           |
|  +-----------------------------+   +-----------------------------+   |
|  | Kural Motoru (rules/engine) |   | Entropi (core/entropy.py)   |   |
|  | - secrets.yaml (20)         |   | - tırnak içi token          |   |
|  | - owasp.yaml (6)            |   | - uzunluğa bağlı eşik       |   |
|  | - dosya kapsamı, placeholder|   | - benign/UUID/yol filtresi  |   |
|  +-----------------------------+   +-----------------------------+   |
|  Bastırma (gitshield: ignore, .gitshieldignore), lockfile istisnası  |
|  Dedupe: (dosya, satır, eşleşen metin) başına en yüksek önem         |
+----------------------------------------------------------------------+
                                  |
                                  v
+----------------------------------------------------------------------+
|  ScanReport / Finding (core/models.py, Pydantic)                     |
+----------------------------------------------------------------------+
           |                      |                         |
           v                      v                         v
  [ --fix: LLM öneri ]    [ Konsol (Rich) ]        [ JSON / SARIF 2.1.0 ]
  ai/remediator.py        formatters/console.py    formatters/sarif.py
  (redakte edilmiş        (sır maskeli)            (sır maskeli;
   bağlam)                                          GitHub Code Scanning)

  Web hattı (web/review.py): Scanner bulguları + PR diff'i
  -> LLM incelemesi -> doğrulayıcı -> kullanıcı onayı -> GitHub
```

---

## 4. Bileşen Ayrıntıları

### 4.1. Diff Ayrıştırıcı (`core/diff_parser.py`)

- **Kaynak:** `--staged` (`git diff --cached`), `--branch REF` (`git diff --end-of-options REF`) veya varsayılan çalışma ağacı (`HEAD`, ilk commit yoksa boş ağaç ile karşılaştırılır).
- **Untracked dosyalar:** Varsayılan çalışma ağacı taramasında `ls-files --others --exclude-standard` ile `.gitignore` dışındaki izlenmeyen dosyalar, tüm satırları eklenmiş gibi (`/dev/null` karşılaştırmasıyla) eklenir. 1 MB'tan büyük dosyalar ve ikili (binary) dosyalar atlanır. `--no-untracked` ile kapatılabilir.
- **Ayrıştırma:** Hunk başlığındaki sayaçlar (`@@ -a,b +c,d @@`) takip edilerek gövde satırları sayılır; `+++`/`---` satırları gövde içinde içerik olarak yorumlanır. Yeni dosya satır numarası her eklenen satır için doğru hesaplanır.
- **Yollar:** Git'in tırnaklı ve escape'li yolları (`"a\303\274.py"`, boşluk, Türkçe karakter) çözülür.
- **Hata:** Git hata kodu döndürürse `GitDiffError` fırlatılır; CLI bunu çıkış kodu 2 ile bildirir.

### 4.2. Kural Motoru (`rules/engine.py`)

- Yerleşik kurallar `gitshield/rules/*.yaml` dosyalarından yüklenir. `--rules-dir` ile verilen dizindeki `*.yaml` dosyaları yerleşik kurallara **eklenir**.
- **Kapsam:** `file_patterns` ve `exclude_patterns`, dosyanın normalize edilmiş tam yolu veya dosya adı üzerinde `fnmatch` ile değerlendirilir.
- **Eşleşme:** Her kural bir satırdaki **tüm** eşleşmeleri (`finditer`) üretir; aynı satırda aynı metin tekrar edilmez.
- **Yer tutucu filtresi:** `skip_placeholders: true` olan kurallarda `value` adlı named group, `changeme`, `example`, `${...}`, `<...>`, `os.getenv(...)` gibi yer tutucu değerlerse atlanır.
- **Dedupe:** `(dosya, satır, eşleşen metin)` anahtarıyla tekilleştirilir; çakışmada en yüksek önem kalır.

### 4.3. Entropi Sezgisi (`core/entropy.py`)

- Yalnızca **tırnak içindeki** 16–128 karakterlik değerler incelenir (`"..."` veya `'...'`).
- Sır karakter kümesi: `A-Za-z0-9+/=_-.`; en az iki karakter sınıfı (küçük, büyük, rakam) şarttır.
- **Hex değerler** (ör. git SHA, SHA-256): yalnızca satırda `secret|token|key|password|pwd|auth|credential` adının `:` veya `=` ile atandığı bir bağlamdaysa değerlendirilir. Eşik taban 3.2.
- **Diğer değerler:** Eşik taban 4.3.
- **Uzunluğa bağlı eşik:** `min(taban, 0.8 · log2(uzunluk))`. Kısa rastgele dizgilerin ulaşamayacağı bir entropiyi istemez.
- **Her zaman dışarıda tutulanlar:** `http(s)://`, `application/`, `text/`, `image/` önekleri; UUID; dosya yolu biçimli değerler; noktalı tanımlayıcılar (`com.example.service`); sürüm numaraları; 4'ten az farklı karakter içeren veya ardışık karakterleri çoğunlukta olan dizgiler.
- **Lockfile istisnası:** `package-lock.json`, `uv.lock`, `go.sum` vb. dosyalarda entropi sezgisi çalışmaz (bütünlük hash'leri); kural motoru çalışmaya devam eder.
- Bulgu kimliği: `ENTROPY-HIGH-001`, önem HIGH, CWE-798. Aynı token bir kural bulgusunda zaten geçiyorsa tekrar bulgu üretilmez.

### 4.4. Tarayıcı ve Bastırma (`core/scanner.py`)

- `scan_diff` her eklenen satır için önce kural motorunu, sonra (açıksa) entropi sezgisini çalıştırır.
- **Satır içi bastırma:** Satırdaki `gitshield: ignore` (büyük/küçük harf duyarsız) o satırdaki tüm bulguları susturur; `gitshield: ignore[ID1,ID2]` yalnızca belirtilen kimlikleri susturur. Bastırma yalnızca aynı satıra etki eder.
- **Dosya bazlı yoksayma:** `load_ignore_file` depo kökündeki `.gitshieldignore` desenlerini okur; `Scanner(ignore_patterns=...)` eşleşen dosyaları taramadan atlar (sonda `/` dizin öneki, başta `**/` kökü de kapsar, `/` içermeyen desen dosya adıyla eşleşir). CLI dosyayı otomatik yükler (`--no-ignore-file` ile kapatılır); web review hattı varsayılan `Scanner()` ile yoksayma uygulamaz.
- Rapor; taranan dosya sayısı, taranan eklenen satır sayısı ve süre bilgilerini taşır.

### 4.5. Düzeltme Önerisi (`ai/remediator.py`, CLI `--fix`)

- Sağlayıcılar: `anthropic`, `gemini`, `openai`. Seçim: `LLM_PROVIDER`, yoksa API anahtarı bulunan ilk sağlayıcı. Model: `LLM_MODEL` veya sağlayıcı varsayılanı.
- **Bağlam:** Bulgunun dosyasından ±8 satır okunur (`>>` ile bulgu satırı işaretlenir). Bu bağlam `redact_secrets` ile temizlenir: kural motorunun sır bulguları (≥4 karakter) ve entropi tokenları `<REDACTED_SECRET>` ile değiştirilir; bulgunun kendi `matched_text`'i ayrıca maskelenir. Bağlamdaki `</code>` etiketi kaçışlanır.
- **Çıktı:** Açıklama ve önerilen değiştirme kodu. Diff/patch olarak uygulanmaz; `Finding.suggested_fix` alanına yazılır ve konsolda gösterilir.
- **Hata davranışı:** Sağlayıcı yoksa, anahtar eksikse, zaman aşımı, HTTP hatası veya boş yanıt olursa kural tarafındaki varsayılan öneri ile birlikte hata mesajı döner. API anahtarı hata metinlerinde yer almaz.
- Zaman aşımı 60 saniye. Anthropic isteğinde çıktı üst sınırı 2048 token'dır.

### 4.6. Çıktı Biçimleri (`formatters/`)

- **Konsol (`console.py`):** Rich tablosu. Sır bulguları `Finding.mask_secret()` ile gösterilir; diğer eşleşmeler olduğu gibi gösterilir.
- **JSON:** `ScanReport` modelinin `model_dump_json` çıktısı. Sır bulguları CLI'da `Finding.redacted()` ile maskelenmiş kopya üzerinden yazılır.
- **SARIF 2.1.0 (`sarif.py`):**
  - `runs[0].tool.driver.rules`: her kural kimliği için bir kez; `security-severity` (CRITICAL 9.5, HIGH 7.5, MEDIUM 5.0, LOW 3.0, INFO 0.0) ve `security`/CWE etiketleri.
  - `level`: CRITICAL/HIGH → `error`, MEDIUM → `warning`, LOW → `note`, INFO → `none`.
  - `locations`: depo köküne göre göreli, `%SRCROOT%` tabanlı URI; `startLine` bulgunun satırı, `startColumn` 1.
  - `partialFingerprints.primaryLocationLineHash`: kural kimliği + dosya + normalize edilmiş satır içeriği + aynı içerikteki sıra numarası üzerinden SHA-256. **Satır numarası kullanılmaz**; böylece satır kayması alarmı yeniden açmaz. Sır içeren satırda ham sır yerine yer tutucu hash'lenir.
  - Sır bulgularının `message` ve `snippet` alanlarında sır maskelenir.
- Dosya çıktısı ve stdout için `--format sarif|json` kullanılır; `--output` verilmezse stdout'a yazılır.

### 4.7. Web Hattı (`gitshield/web/`)

- **Review hattı (`review.py`):** Repo ve PR bilgisi GitHub'dan alınır; diff `GITSHIELD_MAX_DIFF_CHARS` ile sınırlanır (aşan dosyalar atlanmış olarak listelenir). Tarayıcı çalıştırılır (`Scanner().scan_diff`). Sır bulguları (≥6 karakter) hem açıklanmış diff'ten hem bulguların bağlamından LLM'e gitmeden önce `<REDACTED_SECRET>` ile değiştirilir. PR başlığı, açıklaması, diff ve yorumlar prompt'ta "güvenilmeyen veri" olarak etiketlenir.
- **Doğrulayıcı:** İkinci bir LLM geçişi incelemeyi doğrular (doğrulandı / belirsiz / reddedildi); yorumlar kullanıcı onayından sonra GitHub'a gönderilir.
- **LLM bütçesi (`llm.py`):** Her LLM isteği `BudgetedProvider` üzerinden geçer; son 24 saatteki istekler veritabanından sayılır ve `GITSHIELD_MAX_LLM_CALLS_PER_DAY` aşılırsa istek yapılmaz (`0` = sınırsız).
- **Otomatik inceleme bütçesi (`automation.py`):** Arka plan izleyicisinin başlatabileceği review sayısı `GITSHIELD_MAX_AUTO_REVIEWS_PER_DAY` ile sınırlanır; elle başlatılanlar sayılmaz.
- **Akıl yürütme derinliği:** Anthropic için `LLM_EFFORT` (`low`, `medium`, `high`, `xhigh`, `max`; varsayılan `medium`). Geçersiz değerde `medium` kullanılır.
- **Yedek model:** Gemini'de birincil model zaman aşımına uğrar veya 5xx dönerse `LLM_FALLBACK_MODEL` (varsayılan `gemini-3.5-flash`) denenir.
- **Yerel sunucu koruması (`security.py`):**
  - `Host` başlığı yalnızca `127.0.0.1`, `localhost`, `::1` ve `GITSHIELD_ALLOWED_HOSTS` değerlerini kabul eder (DNS rebinding).
  - Güvensiz yöntemler (POST/PUT/PATCH/DELETE) için yerel `Origin` ve `X-GitShield-Client` başlığı şarttır (CSRF).
  - `GITSHIELD_API_TOKEN` ayarlıysa her `/api` isteği `Authorization: Bearer` başlığı veya `gitshield_token` çerezi ister. Token `/?token=...` ile bir kez verilir; çerez HttpOnly ve SameSite=Strict'tir. Karşılaştırma sabit zamanlıdır (`hmac.compare_digest`).
- **Veritabanı:** SQLite (`GITSHIELD_DB`, varsayılan `.gitshield/web.db`).

---

## 5. Veri Modelleri (`core/models.py`)

### 5.1. Severity ve RuleType

- `Severity`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`.
- `RuleType`: `SECRET`, `OWASP`, `ENTROPY`, `DEPENDENCY`. Şu an yerleşik kurallar `SECRET`, `OWASP` ve `ENTROPY` kullanır; `DEPENDENCY` tanımlıdır ama hiçbir yerleşik kural kullanmaz.

### 5.2. Finding (Bulgu)

| Alan | Tür | Açıklama |
|---|---|---|
| `id` | str | Benzersiz bulgu kimliği: `{rule_id}-{dosya}-{satır}-{konum}`. |
| `rule_id` | str | Kural kimliği (ör. `SEC-AWS-001`, `OWASP-A03-SQLI-001`, `ENTROPY-HIGH-001`). |
| `title` | str | Kısa başlık. |
| `description` | str | Açıklama. Entropi bulgusunda entropi değeri içerir. |
| `severity` | Severity | Önem. |
| `rule_type` | RuleType | Kural türü; sır maskelemesi `SECRET` ve `ENTROPY` için uygulanır. |
| `file_path` | str | Depo göreli dosya yolu. |
| `line_number` | int | Eklenen satırın yeni dosyadaki numarası. |
| `matched_text` | str | Eşleşen metin (sır ise ham değer; çıktıya yazılmadan önce maskelenir). |
| `context` | str \| None | Bulunduğu satırın içeriği (kırpılmış). |
| `entropy` | float \| None | Entropi bulgusunda hesaplanan entropi. |
| `cwe` | str \| None | CWE kimliği (ör. `CWE-798`). |
| `suggested_fix` | str \| None | Kuralın öneri metni veya LLM'in `--fix` çıktısı. |
| `diff_patch` | str \| None | Ayrılmış alan; mevcut tarayıcı doldurmaz. |

Yöntemler: `mask_secret()` (≥16 karakter: ilk 4 karakter görünür; kısa değerler tamamen `*`), `redacted()` (SECRET/ENTROPY bulgularında `matched_text`, `context` ve `diff_patch` içindeki değeri maskeler; diğerleri olduğu gibi kopyalanır).

### 5.3. DiffLine ve DiffHunk

- `DiffLine`: `file_path`, `line_number`, `content`, `is_added`.
- `DiffHunk`: `file_path`, `old_start`, `old_count`, `new_start`, `new_count`, `lines`.

### 5.4. ScanReport

`repo_path`, `target_ref` (`working_tree`, `staged` veya ref), `findings`, `scanned_files_count`, `scanned_lines_count`, `execution_time_sec`. Yardımcılar: `has_high` (CRITICAL veya HIGH var mı), `has_critical`.

---

## 6. Çıkış Kodları

| Kod | Durum |
|---|---|
| `0` | Tarama başarılı; HIGH/CRITICAL bulgu yok (veya `--no-fail`). |
| `1` | HIGH veya CRITICAL bulgu var (`--fail-on-critical`, varsayılan). |
| `2` | Tarama çalışamadı: git hatası, geçersiz ref, depo değil, bilinmeyen `--format`. |

GitHub Action bu kodları ayırt eder: `1` job'u başarısız yapar, `2` ve diğer hata kodları da başarısız yapar, `0` geçer.

---

## 7. Güvenlik ve Gizlilik

- **Konsol, JSON ve SARIF:** Sır bulguları maskelenir (ilk 4 karakter, veya tamamen gizli). Ham sır dosyaya ya da stdout'a yazılmaz.
- **CLI `--fix`:** LLM'e giden bağlam `redact_secrets` ile temizlenir (Bölüm 4.5). Model yalnızca maskelenmiş kodu ve bulgu meta verisini görür.
- **Web incelemesi:** Tarayıcının bulduğu sır değerleri LLM'e giden diff ve bulgu bağlamında `<REDACTED_SECRET>` ile değiştirilir. Bu koruma **yalnızca tarayıcının yakaladığı sırları** kapsar; PR açıklaması ve yorumları gibi diğer içerikler olduğu gibi gönderilir ve "güvenilmeyen veri" olarak etiketlenir.
- **Yerel sunucu:** Bölüm 4.7'deki Host, Origin, istemci başlığı ve isteğe bağlı API token korumaları. Sunucu kullanıcının GitHub token'ı ile çalışır, bu nedenle varsayılan bağlama adresi `127.0.0.1`'dir.
- **Ortam değişkenleri:** CLI `.env` dosyasını okumaz; `--fix` için anahtarlar ortamda tanımlı olmalıdır. Web sunucusu `python-dotenv` ile `.env` dosyasını yükler.

---

## 8. Ortam Değişkenleri ve Yapılandırma Özeti

| Değişken | Kullanıldığı yer | Varsayılan |
|---|---|---|
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` | `--fix`, web | — |
| `LLM_PROVIDER`, `LLM_MODEL` | `--fix`, web | otomatik / sağlayıcıya göre |
| `LLM_FALLBACK_MODEL` | web (Gemini) | `gemini-3.5-flash` |
| `LLM_EFFORT` | web (Anthropic) | `medium` |
| `GITSHIELD_MAX_LLM_CALLS_PER_DAY` | web | `200` (`0` sınırsız) |
| `GITSHIELD_MAX_AUTO_REVIEWS_PER_DAY` | web | `20` (`0` sınırsız) |
| `GITSHIELD_MAX_DIFF_CHARS` | web | `150000` |
| `GITSHIELD_AUTO_REVIEW_INTERVAL` | web | `300` (`0` kapalı) |
| `GITSHIELD_API_TOKEN` | web | boş (koruma kapalı) |
| `GITSHIELD_GAMIFICATION` | web | `on` |
| `GITSHIELD_DB`, `GITSHIELD_ALLOWED_HOSTS`, `GITSHIELD_PUBLIC_URL`, `GITSHIELD_REVIEW_LANGUAGE`, `GITHUB_TOKEN` | web | bkz. README |

---

## 9. Bilinen Sınırlamalar

- **Satır bazlı kurallar:** Çok satırlı ifadeler (ör. satır sonunda bölünmüş bir `cursor.execute(` çağrısı) yakalanmaz. AST veya veri akışı analizi yoktur.
- **Entropi yalnızca tırnak içi değerleri görür:** Tırnaksız değişkenlere atanmış rastgele dizgiler sezgiyle yakalanmaz; yalnızca yerleşik regex kuralları çalışır.
- **Kapsam:** OWASP kuralları Python, JavaScript ve TypeScript ile sınırlıdır.
- **Tedarik zinciri:** `DEPENDENCY` türü tanımlıdır ama kural yoktur.
- **Doğrulama yok:** Bulunan sırların canlı olup olmadığı kontrol edilmez.
- **Düzeltmeler:** `--fix` çıktısı öneridir; uygulanmaz ve test edilmez.
- **Kapsam dışı:** Baseline mekanizması henüz yoktur; bastırma satır içi yorumla ya da `.gitshieldignore` ile dosya bazında yapılır.
