"""Go, Java, PHP and Ruby OWASP rules: each rule fires on a risky line and stays quiet on the safe form."""

import pytest

from gitshield.rules.engine import RuleEngine

ENGINE = RuleEngine()


def ids(path, line):
    return {f.rule_id for f in ENGINE.scan_line(path, 1, line)}


# (rule id, file, risky line, safe line)
CASES = [
    # --- Go ---
    ("OWASP-A03-GO-SQLI-007", "db/users.go",
     'rows, err := db.Query(fmt.Sprintf("SELECT * FROM users WHERE id = %s", id))',
     'rows, err := db.Query("SELECT * FROM users WHERE id = $1", id)'),
    ("OWASP-A03-GO-SQLI-007", "db/users.go",
     'db.ExecContext(ctx, "DELETE FROM t WHERE name = \'" + name + "\'")',
     'db.ExecContext(ctx, "DELETE FROM t WHERE name = ?", name)'),
    ("OWASP-A03-GO-CMDI-008", "cmd/run.go",
     'out, _ := exec.Command("sh", "-c", "git log "+ref).Output()',
     'out, _ := exec.Command("git", "log", ref).Output()'),
    ("OWASP-A03-GO-CMDI-008", "cmd/run.go",
     'exec.CommandContext(ctx, "/bin/bash", "-c", script)',
     'exec.CommandContext(ctx, "bash", script)'),
    ("OWASP-A02-GO-HASH-009", "pkg/hash.go", "sum := md5.Sum(data)", "sum := sha256.Sum256(data)"),
    ("OWASP-A02-GO-HASH-009", "pkg/hash.go", "h := sha1.New()", "h := sha512.New()"),
    ("OWASP-A07-GO-TLS-010", "net/client.go",
     "cfg := &tls.Config{InsecureSkipVerify: true}",
     "cfg := &tls.Config{InsecureSkipVerify: false}"),
    # --- Java / Kotlin ---
    ("OWASP-A03-JAVA-SQLI-011", "src/UserDao.java",
     'ResultSet rs = stmt.executeQuery("SELECT * FROM users WHERE id = " + id);',
     'PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE id = ?");'),
    ("OWASP-A03-JAVA-SQLI-011", "src/UserRepo.kt",
     'em.createNativeQuery(String.format("SELECT * FROM t WHERE n = \'%s\'", n))',
     'em.createNativeQuery("SELECT * FROM t WHERE n = :n")'),
    ("OWASP-A03-JAVA-CMDI-012", "src/Shell.java",
     "Process p = Runtime.getRuntime().exec(cmd);",
     "Runtime rt = Runtime.getRuntime();"),
    ("OWASP-A03-JAVA-CMDI-012", "src/Shell.java",
     'new ProcessBuilder("sh", "-c", userCmd).start();',
     'new ProcessBuilder("git", "status").start();'),
    ("OWASP-A08-JAVA-DESER-013", "src/Load.java",
     "ObjectInputStream in = new ObjectInputStream(socket.getInputStream());",
     "ObjectOutputStream out = new ObjectOutputStream(os);"),
    ("OWASP-A02-JAVA-HASH-014", "src/Hash.java",
     'MessageDigest md = MessageDigest.getInstance("MD5");',
     'MessageDigest md = MessageDigest.getInstance("SHA-256");'),
    ("OWASP-A02-JAVA-HASH-014", "src/Hash.java",
     'MessageDigest.getInstance("SHA-1")',
     'MessageDigest.getInstance("SHA-512")'),
    ("OWASP-A02-JAVA-CIPHER-015", "src/Crypto.java",
     'Cipher c = Cipher.getInstance("AES/ECB/PKCS5Padding");',
     'Cipher c = Cipher.getInstance("AES/GCM/NoPadding");'),
    ("OWASP-A02-JAVA-CIPHER-015", "src/Crypto.java",
     'Cipher.getInstance("DES/CBC/PKCS5Padding")',
     'Cipher.getInstance("ChaCha20-Poly1305")'),
    ("OWASP-A02-JAVA-CIPHER-015", "src/Crypto.java",
     'Cipher.getInstance("AES")',
     'Cipher.getInstance("AES/CBC/PKCS5Padding")'),
    # --- PHP ---
    ("OWASP-A03-PHP-SQLI-016", "app/users.php",
     '$r = mysqli_query($conn, "SELECT * FROM users WHERE id = $id");',
     "$r = mysqli_query($conn, $sql);"),
    ("OWASP-A03-PHP-SQLI-016", "app/users.php",
     "$pdo->query('SELECT * FROM users WHERE id = ' . $_GET['id']);",
     "$stmt = $pdo->prepare('SELECT * FROM users WHERE id = ?');"),
    ("OWASP-A03-PHP-CMDI-017", "app/run.php",
     "$out = shell_exec('ls ' . $dir);",
     "$out = shell_exec('ls /var/www');"),
    ("OWASP-A03-PHP-CMDI-017", "app/run.php",
     'system("convert " . $file);',
     "$pdo->exec($sql);"),
    ("OWASP-A03-PHP-EVAL-018", "app/calc.php", "eval($code);", "$parser->eval($expr);"),
    ("OWASP-A08-PHP-DESER-019", "app/session.php",
     "$data = unserialize($_COOKIE['state']);",
     "$data = unserialize($raw, ['allowed_classes' => false]);"),
    ("OWASP-A03-PHP-LFI-020", "app/index.php",
     "include($_GET['page'] . '.php');",
     "include __DIR__ . '/header.php';"),
    ("OWASP-A03-PHP-XSS-021", "app/search.php",
     "echo $_GET['q'];",
     "echo htmlspecialchars($_GET['q'], ENT_QUOTES, 'UTF-8');"),
    ("OWASP-A03-PHP-XSS-021", "views/search.phtml",
     "<?= $_REQUEST['q'] ?>",
     "<?= htmlspecialchars($q) ?>"),
    ("OWASP-A02-PHP-HASH-022", "app/auth.php",
     "$h = md5($password);",
     "$h = password_hash($password, PASSWORD_DEFAULT);"),
    # --- Ruby ---
    ("OWASP-A03-RUBY-SQLI-023", "app/models/user.rb",
     'User.where("name = \'#{params[:name]}\'")',
     'User.where("name = ?", params[:name])'),
    ("OWASP-A03-RUBY-SQLI-023", "app/models/user.rb",
     'ActiveRecord::Base.connection.execute("DELETE FROM logs WHERE id = #{id}")',
     "User.where(name: params[:name])"),
    ("OWASP-A03-RUBY-CMDI-024", "lib/deploy.rb",
     'system("git checkout #{branch}")',
     'system("git", "checkout", branch)'),
    ("OWASP-A03-RUBY-CMDI-024", "lib/deploy.rb",
     "out = `ls #{dir}`",
     "out = `ls /tmp`"),
    ("OWASP-A03-RUBY-CMDI-024", "lib/deploy.rb",
     'stdout, status = Open3.capture2("grep #{pattern} log.txt")',
     'stdout, status = Open3.capture2("grep", pattern, "log.txt")'),
    ("OWASP-A03-RUBY-EVAL-025", "lib/dsl.rb", "eval(params[:code])", "evaluate(params[:code])"),
    ("OWASP-A03-RUBY-EVAL-025", "lib/dsl.rb",
     'klass.class_eval "def #{name}; end"',
     "klass.class_eval do"),
    ("OWASP-A08-RUBY-DESER-026", "lib/cache.rb",
     "obj = Marshal.load(payload)",
     "obj = JSON.parse(payload)"),
    ("OWASP-A08-RUBY-DESER-026", "lib/cache.rb",
     "cfg = YAML.unsafe_load(File.read(path))",
     "cfg = YAML.safe_load(File.read(path))"),
    ("OWASP-A02-RUBY-HASH-027", "lib/token.rb",
     "digest = Digest::MD5.hexdigest(token)",
     "digest = Digest::SHA256.hexdigest(token)"),
    ("OWASP-A03-RUBY-XSS-028", "app/helpers/view_helper.rb",
     "content_tag(:div, comment.body.html_safe)",
     "content_tag(:div, sanitize(comment.body))"),
    ("OWASP-A03-RUBY-XSS-028", "app/views/posts/show.html.erb",
     "<%== @post.body %>",
     "<%= @post.body %>"),
]


@pytest.mark.parametrize("rule_id, path, risky, safe", CASES)
def test_rule_flags_risky_line(rule_id, path, risky, safe):
    assert rule_id in ids(path, risky)


@pytest.mark.parametrize("rule_id, path, risky, safe", CASES)
def test_rule_ignores_safe_line(rule_id, path, risky, safe):
    assert rule_id not in ids(path, safe)


@pytest.mark.parametrize("rule_id, path, risky, safe", CASES)
def test_language_rules_stay_in_their_language(rule_id, path, risky, safe):
    # The same risky text in a Markdown file or in another language must not trigger the rule.
    assert rule_id not in ids("docs/guide.md", risky)
    other = "app/other.py" if not path.endswith(".py") else "app/other.go"
    assert rule_id not in ids(other, risky)


def test_python_eval_rule_does_not_fire_on_php():
    assert "OWASP-A03-EVAL-003" not in ids("app/calc.php", "eval($code);")


def test_every_new_language_has_rules():
    patterns = {p for r in ENGINE.rules if r.rule_type.value == "OWASP" for p in r.file_patterns}
    for ext in ("*.go", "*.java", "*.kt", "*.php", "*.rb", "*.erb"):
        assert ext in patterns


def test_rule_ids_are_unique():
    rule_ids = [r.id for r in ENGINE.rules]
    assert len(rule_ids) == len(set(rule_ids))
