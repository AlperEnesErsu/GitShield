# GitShield — Mimari ve Tasarım Belgesi

## 1. Giriş ve Amaç

**GitShield**, modern yazılım geliştirme süreçlerinde (CI/CD ve lokal geliştirici döngüsü) kod güvenliğini proaktif ve sürtünmesiz hale getirmeyi amaçlayan yeni nesil bir güvenlik motorudur.

Geleneksel SAST çözümleri genellikle monolitik tarama yapar ve binlerce satır sahte pozitif (false positive) üreterek geliştiriciyi boğar. GitShield, **"Diff-Only Contextual Inspection"** (Sadece Değişiklik Odaklı Bağlamsal İnceleme) ve **"Generative Remediation"** (Üretici Otomatik Düzeltme) ilkeleri üzerine inşa edilmiştir.

---

## 2. Temel Tasarım İlkeleri

1. **Diff-First (Yalnızca Değişen Kod):** Tarayıcı, tüm kod tabanını baştan sona taramak yerine `git diff` üzerindeki `+` (eklenen) satırları ve bu satırların 5 satır öncesi/sonrası bağlamını inceler.
2. **Çift Kademeli Tespit (Deterministik + Heuristik):**
   - **Deterministik:** Bilinen kalıplar (AWS Key `AKIA...`, GitHub PAT `ghp_...`, JWT `ey...`, Private Key başlıkları).
   - **Heuristik:** Shannon Entropi Formülü (\( H(X) = -\sum P(x) \log_2 P(x) \)) kullanılarak rastgele üretilmiş yüksek entropili token'lar yakalanır (ör. gizli API anahtarları).
3. **Statik Analiz (OWASP Kuralları):** String concatenation ile birleştirilen ham SQL sorguları, `eval()`, `dangerouslySetInnerHTML`, güvensiz `subprocess.Popen(shell=True)` gibi yaygın zafiyet kalıpları.
4. **AI Destekli Akıllı Düzeltme (Remediation):** Tespit edilen zafiyet bir LLM'e (Gemini / Claude / Ollama) gönderilir; modelden sadece açıklama değil, doğrudan `patch -p1` veya `git apply` ile uygulanabilecek temiz bir **Unified Diff** talep edilir.
5. **Açık Standartlar (SARIF):** Sonuçlar OASIS SARIF (Static Analysis Results Interchange Format) standardına dönüştürülerek GitHub Advanced Security sekmesine doğrudan entegre edilebilir.

---

## 3. Katmanlı Mimari Şeması

```
+-------------------------------------------------------------+
|                         GitShield CLI                       |
|               (Typer + Rich Interactive UI)                |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                      Core Pipeline                          |
|  - Git Diff Extractor (Staged, Unstaged, Branch comparison) |
|  - Patch / Hunk Chunker                                     |
+-------------------------------------------------------------+
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
+------------------------+        +--------------------------+
|  Pattern Engine (YAML) |        | Shannon Entropy Engine   |
|  - Secrets (AWS, JWT)  |        | - Tokenizer              |
|  - OWASP Top 10 Rules  |        | - Entropy Thresholds     |
+------------------------+        +--------------------------+
             \                                 /
              \                               /
               v                             v
+-------------------------------------------------------------+
|                      Finding Normalizer                     |
|           (Pydantic Models: Severity, Line, Rule)           |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                  AI Remediation Engine                      |
|         (LLM Prompting -> Strict Unified Diff)              |
+-------------------------------------------------------------+
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
      [ Rich Terminal ] [ GitHub PR ]    [ SARIF JSON ]
```

---

## 4. Veri Modelleri (Schema)

### 4.1. Finding (Bulgu)
- `rule_id`: Kuralın benzersiz kimliği (örn. `SEC-001`, `OWASP-A03-SQLI`).
- `title`: Kısa açıklama.
- `severity`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`.
- `file_path`: Dosya yolu.
- `line_number`: Hatanın yer aldığı satır numarası.
- `matched_text`: Zafiyetli kod parçası (veya maskelenmiş gizli anahtar).
- `entropy`: Hesaplanan entropi değeri (varsa).
- `suggested_fix`: AI tarafından üretilen çözüm kodu / diff.

---

## 5. Güvenlik ve Gizlilik Garantisi

GitShield, sırları ve kodları tararken şu güvenlik kurallarını işletir:
- **Secret Redaction:** Terminale veya loglara basılan gizli anahtarlar asla açık metin yazdırılmaz; `AKIA************` şeklinde maskelenir.
- **LLM Data Leakage Prevention:** Kod parçaları AI modeline gönderilmeden önce, hardcoded secret tespit edildiyse gerçek secret maskelenir (`<REDACTED_SECRET>`), model yalnızca mimari düzeltmeyi (ör. `os.environ.get(...)` kullanımını) üretir.
