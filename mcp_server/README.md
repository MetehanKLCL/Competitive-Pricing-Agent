# mcp_server — Ne, Neden, Nasıl

Bu dosya MCP entegrasyonunun neden var olduğunu, ne eklediğimizi ve nasıl
test edileceğini anlatır.

---

## Neden var

Projede zaten 14 araç var (`tools/*.py`), ama bunlar sadece Bedrock'un
kendi tool-calling formatında tanımlıydı (`agent/bedrock_agent.py`
içindeki `TOOL_DEFINITIONS`). Bu format **sadece Bedrock'un `converse()`
API'siyle** çalışır — başka bir AI istemcisi (Claude Desktop, Claude Code)
bu araçları hiç kullanamazdı.

**MCP (Model Context Protocol):** AI istemcilerin araçlara standart bir
şekilde bağlanmasını sağlayan protokol. USB benzetmesi: USB'den önce her
cihazın kendi kablosu vardı, USB gelince "tek standart, her şey bağlanır"
oldu. MCP de aynısını AI + araç bağlantısı için yapıyor.

`mcp_server/server.py`, aynı 14 fonksiyonu **hiç kopyalamadan** MCP
standardına göre "dışarıya açıyor". Artık MCP destekleyen her istemci
(Claude Desktop, Claude Code, ileride başka araçlar) bunlara bağlanabilir.

**Ana pricing agent (`agent/bedrock_agent.py`) hiç değişmedi.** O hâlâ
kendi Bedrock native tool-calling'ini kullanıyor, 7/24 Lambda'da otomatik
çalışmaya devam ediyor. MCP, var olan sisteme **eklenen**, onu
**değiştirmeyen** ayrı bir erişim katmanı.

---

## Dosya haritası

```
Competitive-Pricing-Agent/
├── requirements.txt        ← mcp[cli] eklendi
├── mcp_server/
│   ├── README.md            ← bu dosya
│   ├── __init__.py          ← boş, "burası bir Python paketi" der
│   └── server.py            ← 14 aracı MCP olarak duyuran kod
```

---

## `requirements.txt` — ne indirdik

```
mcp[cli]>=1.2.0
```

Anthropic'in resmi Python MCP kütüphanesi. `[cli]` eki, test/debug için
ekstra komut satırı araçları (MCP Inspector gibi) getirir. `pip install`
ile kuruldu — hiçbir AWS kaynağına dokunmadan, sadece local paket kurulumu.

---

## `mcp_server/server.py` — satır satır

```python
from tools import (
    query_sales as _query_sales,
    check_competitors as _check_competitors,
    ...
)

mcp = FastMCP("heweso-pricing-tools")

@mcp.tool()
def query_sales(product_id: str, minutes: int = 60) -> dict:
    """Fetches sales for a product in the last N minutes, plus current/min/base price."""
    return _query_sales(product_id, minutes)
```

**Import kısmı:** Var olan 14 fonksiyonu içeri aktarıp her birine
`as _query_sales` gibi alt-çizgili takma isim veriyoruz. Neden? Çünkü
aşağıda **aynı isimle yeni bir fonksiyon** tanımlıyoruz — ikisi çakışmasın
diye orijinaline farklı isim veriyoruz.

**`mcp = FastMCP("heweso-pricing-tools")`** — MCP sunucusunun kendisini
oluşturur. String sadece bir isim etiketi, bağlanan istemci bu isimle görür.

**`@mcp.tool()` decorator'ı — en önemli kısım.** Bu satır "bu fonksiyonu
MCP aracı olarak duyur" demek. FastMCP şunlara bakarak otomatik bir JSON
şema üretir:
- **Tip ipuçları** (`product_id: str, minutes: int = 60`) → "iki parametre
  alır, biri metin, biri sayı, ikincisi opsiyonel"
- **Docstring** (`"""Fetches sales..."""`) → istemci bu açıklamayı okuyup
  "bu aracı ne zaman çağırmalıyım" diye anlar

Bu, Bedrock'taki `TOOL_DEFINITIONS`'ı elle JSON olarak yazdığımıza
benzer — ama burada **otomatik**, Python tip ipuçlarından üretiliyor.

**`return _query_sales(...)`** — asıl işi orijinal fonksiyona devrediyor.
Bu wrapper fonksiyonların içinde **hiçbir yeni hesaplama yok**, hepsi
`tools/*.py`'de yaşamaya devam ediyor. Bu kalıp 14 aracın hepsinde aynı.

**En alttaki başlatma kodu:**
```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```
`transport="stdio"` = "terminal girişi/çıkışı üzerinden konuş" demek.
Claude Desktop veya Claude Code bu script'i arka planda çalıştırır ve
onunla stdin/stdout üzerinden mesajlaşır — network portu açmaya gerek yok,
en basit bağlantı yöntemi budur.

`if __name__ == "__main__":` bloğunun içinde olduğu için, dosyayı sadece
**import** ettiğimizde (kontrol amaçlı) bu satır çalışmaz — sunucu gerçek
anlamda ancak `python3 -m mcp_server.server` çalıştırıldığında başlar.

---

## Neyi doğruladık

Sunucuyu gerçekten başlatmadan (terminal kilitlenmesin diye), sadece
"14 araç doğru kaydoldu mu" kontrol edildi:

```python
tools = await mcp.list_tools()
```

Çıktı 14 araç ismini listeledi, hepsi doğru — `@mcp.tool()`
decorator'larının hatasız çalıştığının kanıtı. Bu adımda hiçbir AWS
kaynağına bağlanılmadı, sadece Python objelerinin doğru kurulduğu
kontrol edildi.

---

## Nasıl bağlanılır / test edilir

### Claude Code'a bağlama (en kolay yol) — DOĞRULANDI (2026-07-01)

Düz terminalde (bu sohbetin dışında), proje klasöründe:
```bash
claude mcp add heweso-pricing -e PYTHONPATH="/Users/metehankilicli/Desktop/DE-Projects/Competitive-Pricing-Agent" -- /opt/anaconda3/bin/python3 -m mcp_server.server
```

**Neden bare `python3` değil, tam yol + PYTHONPATH:** İlk denemede
`claude mcp add heweso-pricing -- python3 -m mcp_server.server` ile
kaydettik ama bağlantı başarısız oldu (`✘ Failed to connect`). Sebep:
Claude Code bu sunucuyu proje klasörünün dışında, farklı bir Python
ortamından başlatıyor — `python3` conda `base` ortamındaki paketleri
(`mcp`, `boto3`, `dotenv`) göremiyor, `mcp_server` modülünü de bulamıyor.

Çözüm: `which python3` ile tam yolu bul (`/opt/anaconda3/bin/python3`),
`-e PYTHONPATH=<proje kökü>` ile de "modülleri nerede arayacağını" proje
klasörüne sabitle. `claude mcp list` çalıştırıp `heweso-pricing` yanında
`✔ Connected` görmelisin — `✘ Failed to connect` görürsen bu adımı
tekrarla.

Bu komut **hiçbir AI modeli çağırmaz** — sadece "bu MCP sunucusunu tanı"
diye bir ayar kaydı yazar (git remote add gibi düşün). Sıfır maliyet.

Sonra herhangi bir Claude Code sohbetinde:
> "heweso-pricing MCP sunucusundaki check_sales_trend aracını PROD-001
> için çağır"

Claude bunu gerçekten çağırır, DynamoDB'den veri çeker, sonucu gösterir —
Bedrock'a hiç dokunmadan. **Test edildi, çalışıyor** — `check_sales_trend`
aracı çağrıldı, `NO_DATA` sonucu döndü (simülasyon kapalıyken doğru sonuç).

**Maliyet notu:** Araç çağrısının kendisi (DynamoDB okuma) neredeyse
bedava. Sohbetin kendisi senin zaten kullandığın Claude Code planının
parçası. `run_analytics` aracı Athena'ya sorgu gönderir — taranan veri
kadar ücretlendirilir (Athena Console'dan elle sorgu çalıştırmakla aynı
seviyede, kuruşlar).

### Claude Desktop'a bağlama

`~/Library/Application Support/Claude/claude_desktop_config.json` dosyasına:
```json
{
  "mcpServers": {
    "heweso-pricing": {
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/Users/metehankilicli/Desktop/DE-Projects/Competitive-Pricing-Agent"
    }
  }
}
```

### MCP Inspector (görsel debug arayüzü)

```bash
npx @modelcontextprotocol/inspector python3 -m mcp_server.server
```
Tarayıcıda bir arayüz açılır, her aracı tek tek, parametrelerini elle
girerek deneyebilirsin — Postman'in MCP versiyonu gibi düşün.

---

## Şu an otomatik mi çalışıyor?

Hayır — dbt gibi bu da **yerel, manuel bir yetenek**. AWS'ye deploy
edilmedi, EventBridge kuralı yok. Ana pricing agent'ın 7/24 otonom
çalışmasını hiç etkilemiyor; tamamen ayrı, isteğe bağlı bir erişim yolu.
