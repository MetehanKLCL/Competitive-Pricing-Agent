const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
p.author = "Heweso";
p.title = "Heweso Pricing Agent — Satış Sunumu";

// ── Palette (no #) ────────────────────────────────────────────────
const INK    = "16233F"; // dark navy bg
const NAVY   = "1E2761"; // primary
const ICE    = "CADCFC"; // light blue
const TINT   = "EEF2FB"; // card tint (light)
const TINT2  = "E7EDF9";
const ACCENT = "00A896"; // growth mint
const ACCENTD= "007A6B"; // darker mint (text on light)
const LOSS   = "C24A38"; // muted red
const LOSSBG = "F7E9E6";
const MUTED  = "5A6B85";
const INKTXT = "1B2A44";
const WHITE  = "FFFFFF";

const HSER = "Cambria";   // header serif (safe)
const BODY = "Calibri";   // body sans (safe)

const W = 13.33, H = 7.5, LM = 0.62, CW = W - LM * 2;

const shadow = () => ({ type: "outer", color: "9AA6BC", blur: 6, offset: 3, angle: 90, opacity: 0.35 });

function bgDark(s){ s.background = { color: INK };
  s.addShape(p.ShapeType.ellipse, { x: 10.6, y: -2.2, w: 5.2, h: 5.2, fill: { color: ACCENT, transparency: 86 }, line: { type: "none" } });
  s.addShape(p.ShapeType.ellipse, { x: -1.6, y: 5.1, w: 4.0, h: 4.0, fill: { color: NAVY, transparency: 55 }, line: { type: "none" } });
}

function title(s, kicker, ttl, dark){
  const kc = dark ? ACCENT : ACCENTD;
  const tc = dark ? WHITE : NAVY;
  s.addText(kicker.toUpperCase(), { x: LM, y: 0.44, w: CW, h: 0.3, fontFace: BODY, fontSize: 12, bold: true, color: kc, charSpacing: 2, margin: 0 });
  s.addText(ttl, { x: LM, y: 0.72, w: CW, h: 0.7, fontFace: HSER, fontSize: 32, bold: true, color: tc, margin: 0 });
}

function numCircle(s, x, y, n, d){
  const dd = d || 0.5;
  s.addShape(p.ShapeType.ellipse, { x, y, w: dd, h: dd, fill: { color: ACCENT }, line: { type: "none" } });
  s.addText(String(n), { x, y, w: dd, h: dd, align: "center", valign: "middle", fontFace: BODY, fontSize: dd > 0.55 ? 20 : 17, bold: true, color: WHITE, margin: 0 });
}

// ── Slide 1 — Cover ───────────────────────────────────────────────
(() => {
  const s = p.addSlide(); bgDark(s);
  s.addText("HEWESO PLATFORM   ·   ÜRÜN SUNUMU", { x: LM, y: 2.15, w: CW, h: 0.35, fontFace: BODY, fontSize: 13, bold: true, color: ICE, charSpacing: 3, margin: 0 });
  s.addText("Otonom Rekabetçi Fiyatlandırma", { x: LM, y: 2.55, w: 11.2, h: 1.1, fontFace: HSER, fontSize: 46, bold: true, color: WHITE, margin: 0 });
  s.addText("Perakendecileriniz için 7/24 marj koruması ve gelir optimizasyonu", { x: LM, y: 3.7, w: 10.4, h: 0.6, fontFace: BODY, fontSize: 19, color: ICE, margin: 0 });
  s.addShape(p.ShapeType.line, { x: LM, y: 4.5, w: 2.6, h: 0, line: { color: ACCENT, width: 3 } });
  s.addText("Hazırlayan: [Ad Soyad]      ·      [Tarih]", { x: LM, y: 6.55, w: CW, h: 0.35, fontFace: BODY, fontSize: 12, color: "8FA0BE", margin: 0 });
  s.addNotes("Açılış. Konumlandırma: Heweso platformuna eklenecek premium bir otonom fiyatlandırma yetkinliği. İzleyici: Heweso yönetimi. Değer iki katmanlı: perakendeci (marj+gelir) ve Heweso (farklılaşma+bağlılık).");
})();

// ── Slide 2 — Yönetici Özeti ──────────────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Genel Bakış", "Yönetici Özeti", false);
  const cards = [
    ["Ne sunuyoruz", "Heweso platformuna gömülü, perakendecilerin fiyatlarını rakiplere karşı otonom yöneten bir modül."],
    ["Perakendeci için değer", "Korunan marj ve geri kazanılan satış — sıfır manuel iş, sürekli optimize edilmiş fiyat."],
    ["Heweso için değer", "Rakip altyapılarda olmayan bir yetkinlik: farklılaşma, artan müşteri bağlılığı ve upsell fırsatı."],
  ];
  const cw = 3.83, gap = 0.32, y = 2.15, ch = 3.9;
  cards.forEach((c, i) => {
    const x = LM + i * (cw + gap);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.1, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    numCircle(s, x + 0.35, y + 0.4, i + 1, 0.62);
    s.addText(c[0], { x: x + 0.35, y: y + 1.25, w: cw - 0.7, h: 0.6, fontFace: HSER, fontSize: 19, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: x + 0.35, y: y + 1.95, w: cw - 0.7, h: 1.7, fontFace: BODY, fontSize: 14.5, color: INKTXT, lineSpacingMultiple: 1.1, margin: 0 });
  });
  s.addNotes("Yönetici özeti: tek slaytta ne, kime, ne fayda. Perakendeci faydası satılabilirliği sağlar; Heweso faydası satın alma gerekçesidir.");
})();

// ── Slide 3 — Pazar Dinamikleri ───────────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Bağlam", "Pazar Dinamikleri", false);
  s.addText("Fiyat artık statik bir karar değil.", { x: LM, y: 1.5, w: CW, h: 0.4, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0 });
  const cols = [
    ["Sürekli fiyat hareketi", "Rakipler gün içinde fiyatlarını defalarca değiştiriyor; statik fiyat geride kalıyor."],
    ["Daralan marjlar", "Özellikle elektronikte hata payı düşük; yanlış fiyat hem satış hem kâr kaybettiriyor."],
    ["Yeni rekabet cephesi", "Fiyatı sürekli ve doğru yönetmek, kazananı belirleyen faktör haline geldi."],
  ];
  const cw = 3.83, gap = 0.32, y = 2.3, ch = 3.3;
  cols.forEach((c, i) => {
    const x = LM + i * (cw + gap);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.1, fill: { color: WHITE }, line: { color: TINT2, width: 1 }, shadow: shadow() });
    s.addShape(p.ShapeType.ellipse, { x: x + 0.35, y: y + 0.4, w: 0.62, h: 0.62, fill: { color: TINT }, line: { type: "none" } });
    s.addText(String(i + 1), { x: x + 0.35, y: y + 0.4, w: 0.62, h: 0.62, align: "center", valign: "middle", fontFace: HSER, fontSize: 22, bold: true, color: ACCENTD, margin: 0 });
    s.addText(c[0], { x: x + 0.35, y: y + 1.2, w: cw - 0.7, h: 0.75, fontFace: HSER, fontSize: 18, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: x + 0.35, y: y + 1.95, w: cw - 0.7, h: 1.2, fontFace: BODY, fontSize: 14.5, color: INKTXT, lineSpacingMultiple: 1.1, margin: 0 });
  });
  s.addNotes("Bağlam slaytı: neden şimdi. Rekabet baskısı + daralan marj = fiyat yönetimi stratejik hale geldi.");
})();

// ── Slide 4 — Perakendecilerinizin Sorunu ─────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Problem", "Perakendecilerinizin Sorunu", false);
  s.addText("Bugün elle çözülmeye çalışılıyor — ve çözülemiyor.", { x: LM, y: 1.5, w: CW, h: 0.4, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0 });
  const items = [
    ["Yavaş tepki", "Manuel yeniden fiyatlandırma rakibin hızına yetişemez; tepki saatler, hatta günler alır."],
    ["Marj erozyonu", "Panikle yapılan indirimler çoğu zaman gereğinden derin; kâr sessizce erir."],
    ["Yanlış tepki", "Her geçici indirime atlamak kârı yakar; görmezden gelmek satış kaybettirir."],
    ["Görünürlük eksikliği", "Hangi üründe ne zaman geride kalındığı zamanında görülemez."],
  ];
  const cw = 5.83, gap = 0.35, ch = 1.85, y0 = 2.2, gy = 0.35;
  items.forEach((c, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = LM + col * (cw + gap), y = y0 + row * (ch + gy);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.09, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    s.addText(c[0], { x: x + 0.4, y: y + 0.28, w: cw - 0.8, h: 0.5, fontFace: HSER, fontSize: 18, bold: true, color: LOSS, margin: 0 });
    s.addText(c[1], { x: x + 0.4, y: y + 0.82, w: cw - 0.8, h: 0.9, fontFace: BODY, fontSize: 14, color: INKTXT, lineSpacingMultiple: 1.08, margin: 0 });
  });
  s.addNotes("Problem = perakendecinizin acısı. Bu, platformunuzun çözebileceği bir fırsat. Dört maddede: yavaşlık, marj erozyonu, yanlış tepki, körlük.");
})();

// ── Slide 5 — Mevcut Durumun Maliyeti (stat callouts) ─────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "İş Vakası", "Mevcut Durumun Maliyeti", false);
  s.addText("Örnek: orta ölçekli bir elektronik perakendecisi", { x: LM, y: 1.5, w: CW, h: 0.35, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0 });
  s.addShape(p.ShapeType.roundRect, { x: LM, y: 1.95, w: CW, h: 0.62, rectRadius: 0.06, fill: { color: TINT }, line: { type: "none" } });
  s.addText("Yıllık online ciro ₺120M      ·      rekabete duyarlı SKU cirosu ₺48M      ·      ortalama brüt marj %12",
    { x: LM + 0.2, y: 1.95, w: CW - 0.4, h: 0.62, valign: "middle", fontFace: BODY, fontSize: 14.5, bold: true, color: NAVY, margin: 0 });
  const stats = [
    ["₺720K", "Kaçan yıllık satış (ciro)", "tepki gecikmesi"],
    ["₺288K", "Erisen yıllık marj", "gereksiz indirim derinliği"],
    ["≈ ₺374K", "Kâra toplam yıllık etki", "her yıl tekrar eder"],
  ];
  const cw = 3.83, gap = 0.32, y = 3.05, ch = 2.75;
  stats.forEach((c, i) => {
    const x = LM + i * (cw + gap);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.1, fill: { color: LOSSBG }, line: { type: "none" }, shadow: shadow() });
    s.addText(c[0], { x: x + 0.25, y: y + 0.42, w: cw - 0.5, h: 1.0, align: "center", fontFace: HSER, fontSize: 46, bold: true, color: LOSS, margin: 0 });
    s.addText(c[1], { x: x + 0.25, y: y + 1.5, w: cw - 0.5, h: 0.5, align: "center", fontFace: BODY, fontSize: 15, bold: true, color: INKTXT, margin: 0 });
    s.addText(c[2], { x: x + 0.25, y: y + 1.98, w: cw - 0.5, h: 0.4, align: "center", fontFace: BODY, fontSize: 12, italic: true, color: MUTED, margin: 0 });
  });
  s.addText("Tüm rakamlar örnek varsayıma dayalıdır; gerçek verilerle güncellenir.  (K = bin ₺)", { x: LM, y: 6.05, w: CW, h: 0.3, fontFace: BODY, fontSize: 11, italic: true, color: MUTED, margin: 0 });
  s.addNotes("Hesap: ciro kaybı ₺720K (₺48M x %1,5). Marj kaybı ₺288K (₺14,4M reaktif ciro x 2 puan aşırı indirim). Kâra etki = 720K x %12 (86K) + 288K = ~374K/yıl. Rakamlar örnek; gerçek veriyle değişir.");
})();

// ── Slide 6 — Çözüm ───────────────────────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Çözüm", "Otonom Fiyatlandırma Modülü", false);
  s.addText("Heweso platformuna gömülü, sürekli çalışan bir fiyatlandırma zekâsı. Rakip fiyatları izler, doğru kararı verir, fiyatı otomatik uygular ve sonucu değerlendirir — perakendeci hiçbir şey yapmadan, tanımlı kuralların içinde.",
    { x: LM, y: 2.1, w: 6.1, h: 3.4, fontFace: BODY, fontSize: 17, color: INKTXT, lineSpacingMultiple: 1.25, margin: 0 });
  const chips = [
    ["Kesintisiz izleme", "Rakip fiyatları ve satış hızı 7/24 takip edilir."],
    ["Akıllı karar", "Gereken minimum fiyat ayarı, tam zamanında."],
    ["Otomatik uygulama", "Karar anında hayata geçer ve loglanır."],
  ];
  const x = 7.1, cw = 5.6, ch = 1.28, y0 = 2.05, gy = 0.28;
  chips.forEach((c, i) => {
    const y = y0 + i * (ch + gy);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.09, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    numCircle(s, x + 0.32, y + 0.34, i + 1, 0.6);
    s.addText(c[0], { x: x + 1.15, y: y + 0.22, w: cw - 1.4, h: 0.4, fontFace: HSER, fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: x + 1.15, y: y + 0.63, w: cw - 1.4, h: 0.55, fontFace: BODY, fontSize: 13.5, color: INKTXT, margin: 0 });
  });
  s.addNotes("Çözümü tek cümlede: gömülü, otonom, kurallı fiyatlandırma. Sağdaki üç yetenek: izle, karar ver, uygula.");
})();

// ── Slide 7 — Nasıl Çalışır (process) ─────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Süreç", "Nasıl Çalışır", false);
  const steps = [
    ["İzle", "Satış hızı ve rakip fiyatları"],
    ["Analiz Et", "Geçici mi, yapısal mı?"],
    ["Karar Ver", "Tam gereken fiyat ayarı"],
    ["Uygula", "Fiyatı otomatik güncelle"],
    ["Değerlendir", "Sonucu ölç, gerekirse devret"],
  ];
  const n = steps.length, bw = 2.18, gap = (CW - bw * n) / (n - 1), y = 2.55, bh = 2.7;
  steps.forEach((c, i) => {
    const x = LM + i * (bw + gap);
    s.addShape(p.ShapeType.roundRect, { x, y, w: bw, h: bh, rectRadius: 0.09, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    numCircle(s, x + bw / 2 - 0.33, y + 0.35, i + 1, 0.66);
    s.addText(c[0], { x: x + 0.15, y: y + 1.2, w: bw - 0.3, h: 0.5, align: "center", fontFace: HSER, fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: x + 0.15, y: y + 1.72, w: bw - 0.3, h: 0.85, align: "center", fontFace: BODY, fontSize: 13, color: INKTXT, lineSpacingMultiple: 1.05, margin: 0 });
    if (i < n - 1) s.addText("›", { x: x + bw + gap / 2 - 0.2, y: y + 0.6, w: 0.4, h: 0.6, align: "center", valign: "middle", fontFace: BODY, fontSize: 30, bold: true, color: ACCENT, margin: 0 });
  });
  s.addText("Sürekli döngü — her turda öğrenir ve bir sonraki kararı iyileştirir.", { x: LM, y: 5.65, w: CW, h: 0.4, align: "center", fontFace: BODY, fontSize: 14, italic: true, color: MUTED, margin: 0 });
  s.addNotes("Beş adımlı sürekli döngü: gözle-düşün-karar-aksiyon-değerlendir. Şeffaflık verir; teknik jargon yok.");
})();

// ── Slide 8 — Neden Farklı (comparison) ───────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Farklılaşma", "Neden Farklı", false);
  const rows = [
    ["Her indirime tepki verir", "Geçici promosyonu yapısal hareketten ayırır"],
    ["Rakibi körü körüne eşitler", "Kârı korumak için gereken minimumu yapar"],
    ["Sabit, elle yazılmış kurallar", "Sonuçtan öğrenir, zamanla iyileşir"],
    ["Zayıf sınır kontrolü", "Fiyat tabanının altına asla inmez"],
  ];
  const lw = 5.83, gap = 0.35, x2 = LM + lw + gap, y0 = 2.35, rh = 0.92, gy = 0.14;
  // headers
  s.addShape(p.ShapeType.roundRect, { x: LM, y: 1.7, w: lw, h: 0.55, rectRadius: 0.06, fill: { color: LOSSBG }, line: { type: "none" } });
  s.addText("Sıradan yeniden fiyatlandırma", { x: LM + 0.3, y: 1.7, w: lw - 0.6, h: 0.55, valign: "middle", fontFace: HSER, fontSize: 15, bold: true, color: LOSS, margin: 0 });
  s.addShape(p.ShapeType.roundRect, { x: x2, y: 1.7, w: lw, h: 0.55, rectRadius: 0.06, fill: { color: "E1F3EF" }, line: { type: "none" } });
  s.addText("Heweso Pricing Agent", { x: x2 + 0.3, y: 1.7, w: lw - 0.6, h: 0.55, valign: "middle", fontFace: HSER, fontSize: 15, bold: true, color: ACCENTD, margin: 0 });
  rows.forEach((c, i) => {
    const y = y0 + i * (rh + gy);
    s.addShape(p.ShapeType.roundRect, { x: LM, y, w: lw, h: rh, rectRadius: 0.07, fill: { color: TINT }, line: { type: "none" } });
    s.addText(c[0], { x: LM + 0.35, y, w: lw - 0.7, h: rh, valign: "middle", fontFace: BODY, fontSize: 14.5, color: "6B5450", margin: 0 });
    s.addShape(p.ShapeType.roundRect, { x: x2, y, w: lw, h: rh, rectRadius: 0.07, fill: { color: "EAF7F4" }, line: { type: "none" } });
    s.addText(c[1], { x: x2 + 0.35, y, w: lw - 0.7, h: rh, valign: "middle", fontFace: BODY, fontSize: 14.5, bold: true, color: INKTXT, margin: 0 });
  });
  s.addNotes("Farkı somutlaştır: panik yapmaz, körü körüne eşitlemez, öğrenir, sınır tanır. Sol=piyasa standardı, sağ=biz.");
})();

// ── Slide 9 — Kendini Optimize Eden Strateji (line chart) ─────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Öğrenme", "Kendini Optimize Eden Strateji", false);
  s.addText("Sistem her fiyat kararının sonucunu ölçer ve öğrenir (pekiştirmeli öğrenme). Hangi indirim düzeyinin en çok geliri getirdiğini zamanla kendisi bulur — statik kurallar gibi yerinde saymaz, kullandıkça daha iyi çalışır.",
    { x: LM, y: 2.1, w: 5.7, h: 3.2, fontFace: BODY, fontSize: 17, color: INKTXT, lineSpacingMultiple: 1.25, margin: 0 });
  // Shape-based ascending trend (renders reliably in every app)
  s.addText("Optimal fiyat isabeti — zamanla (%)", { x: 6.7, y: 1.95, w: 6.0, h: 0.4, fontFace: HSER, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  const vals = [42, 49, 56, 61, 67, 72, 76, 79];
  const px0 = 6.9, baseY = 5.55, plotW = 5.7, barW = 0.46;
  const gap = (plotW - vals.length * barW) / (vals.length - 1);
  const hMin = 0.55, hMax = 2.75, vMin = 40, vMax = 82;
  s.addShape(p.ShapeType.line, { x: px0 - 0.15, y: baseY, w: plotW + 0.25, h: 0, line: { color: "D5DCE8", width: 1 } });
  vals.forEach((v, i) => {
    const h = hMin + (v - vMin) / (vMax - vMin) * (hMax - hMin);
    const x = px0 + i * (barW + gap), y = baseY - h;
    s.addShape(p.ShapeType.roundRect, { x, y, w: barW, h, rectRadius: 0.04, fill: { color: ACCENT, transparency: Math.max(0, 45 - i * 6) }, line: { type: "none" } });
    s.addText(String(v), { x: x - 0.15, y: y - 0.32, w: barW + 0.3, h: 0.28, align: "center", fontFace: BODY, fontSize: 9.5, bold: true, color: ACCENTD, margin: 0 });
    s.addText("H" + (i + 1), { x: x - 0.15, y: baseY + 0.08, w: barW + 0.3, h: 0.25, align: "center", fontFace: BODY, fontSize: 9.5, color: MUTED, margin: 0 });
  });
  s.addText("İllüstratif: sistem veri biriktikçe daha isabetli fiyat verir.", { x: 6.7, y: 6.35, w: 6.0, h: 0.3, fontFace: BODY, fontSize: 11, italic: true, color: MUTED, margin: 0 });
  s.addNotes("Epsilon-greedy'yi düz dille: keşfet-öğren-iyileş. Grafik illüstratif; rekabet avantajının zamanla büyüdüğünü gösterir.");
})();

// ── Slide 10 — Yönetişim ve Kontrol ───────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Güven", "Yönetişim ve Kontrol", false);
  s.addText("Otonom, ama kontrollü — 'başıboş bot' değil.", { x: LM, y: 1.5, w: CW, h: 0.4, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0 });
  const items = [
    ["Fiyat tabanı ve tavanı", "Tanımlı sınırların dışına asla çıkamaz."],
    ["Tam denetim kaydı", "Her karar, gerekçesiyle birlikte loglanır."],
    ["İnsan onay eşiği", "Strateji tükendiğinde otomatik olarak yetkiliye devreder."],
    ["Tam görünürlük", "Tüm kararlar ve etkileri denetim panosunda izlenir."],
  ];
  const y0 = 2.25, rh = 0.95, gy = 0.2;
  items.forEach((c, i) => {
    const y = y0 + i * (rh + gy);
    s.addShape(p.ShapeType.roundRect, { x: LM, y, w: CW, h: rh, rectRadius: 0.07, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    numCircle(s, LM + 0.3, y + rh / 2 - 0.28, i + 1, 0.56);
    s.addText(c[0], { x: LM + 1.15, y, w: 3.6, h: rh, valign: "middle", fontFace: HSER, fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: LM + 4.9, y, w: CW - 5.2, h: rh, valign: "middle", fontFace: BODY, fontSize: 14.5, color: INKTXT, margin: 0 });
  });
  s.addNotes("Kurumsal alıcının en büyük endişesi: bot çıldırır mı? Cevap: tavan/taban, denetim izi, insan devri, tam görünürlük.");
})();

// ── Slide 11 — İş Etkisi ve ROI (dark, key slide) ─────────────────
(() => {
  const s = p.addSlide(); bgDark(s);
  title(s, "Getiri", "İş Etkisi ve ROI", true);
  s.addText("Perakendeci düzeyinde — örnek senaryo", { x: LM, y: 1.55, w: CW, h: 0.35, fontFace: BODY, fontSize: 14, bold: true, color: ICE, charSpacing: 1, margin: 0 });
  const stats = [
    ["+₺720K", "Yıllık ciro", "geri kazanılan satış"],
    ["+₺288K", "Korunan yıllık marj", "aşırı indirimin önlenmesi"],
    ["~%2,6", "Kâr artışı", "toplam yıllık etki"],
    ["~15 sa/hf", "Manuel iş", "ortadan kalkan fiyat işi"],
  ];
  const cw = 2.86, gap = 0.28, y = 2.0, ch = 2.05;
  stats.forEach((c, i) => {
    const x = LM + i * (cw + gap);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.1, fill: { color: "1E3050" }, line: { type: "none" } });
    s.addText(c[0], { x: x + 0.15, y: y + 0.28, w: cw - 0.3, h: 0.8, align: "center", fontFace: HSER, fontSize: 33, bold: true, color: ACCENT, margin: 0 });
    s.addText(c[1], { x: x + 0.15, y: y + 1.12, w: cw - 0.3, h: 0.4, align: "center", fontFace: BODY, fontSize: 14, bold: true, color: WHITE, margin: 0 });
    s.addText(c[2], { x: x + 0.15, y: y + 1.5, w: cw - 0.3, h: 0.45, align: "center", fontFace: BODY, fontSize: 11.5, italic: true, color: "9FB0CE", margin: 0 });
  });
  s.addText("Heweso düzeyinde", { x: LM, y: 4.35, w: CW, h: 0.35, fontFace: BODY, fontSize: 14, bold: true, color: ICE, charSpacing: 1, margin: 0 });
  const hv = [
    ["Farklılaşma", "Rakip platformlarda olmayan premium yetkinlik."],
    ["Bağlılık", "Perakendeci churn'ü azalır, platform daha yapışkan olur."],
    ["Büyüme", "Upsell ve ARPU artışı için yeni gelir kanalı."],
  ];
  const hw = 3.83, hg = 0.32, hy = 4.75, hh = 1.25;
  hv.forEach((c, i) => {
    const x = LM + i * (hw + hg);
    s.addShape(p.ShapeType.roundRect, { x, y: hy, w: hw, h: hh, rectRadius: 0.09, fill: { color: ACCENT, transparency: 82 }, line: { color: ACCENT, width: 1 } });
    s.addText(c[0], { x: x + 0.28, y: hy + 0.16, w: hw - 0.5, h: 0.4, fontFace: HSER, fontSize: 16, bold: true, color: WHITE, margin: 0 });
    s.addText(c[1], { x: x + 0.28, y: hy + 0.58, w: hw - 0.5, h: 0.6, fontFace: BODY, fontSize: 13, color: ICE, margin: 0 });
  });
  s.addText("Rakamlar örnek varsayıma dayalıdır.", { x: LM, y: 6.7, w: CW, h: 0.3, fontFace: BODY, fontSize: 11, italic: true, color: "8FA0BE", margin: 0 });
  s.addNotes("Anahtar slayt. Sert ROI perakendeci katmanında (satılabilirlik kanıtı). Heweso katmanı satın alma gerekçesi: farklılaşma, bağlılık, büyüme.");
})();

// ── Slide 12 — Uygulama ve Mimari ─────────────────────────────────
(() => {
  const s = p.addSlide(); s.background = { color: WHITE };
  title(s, "Teknik Güvenilirlik", "Uygulama ve Mimari", false);
  const items = [
    ["Buluta özgü (AWS)", "Yönetilen, güvenilir bulut servisleri üzerinde çalışır."],
    ["Ölçeklenebilir", "Tek üründen tüm kataloğa; yükle birlikte büyür."],
    ["Güvenli", "Erişim kontrolü ve uçtan uca denetim izi."],
    ["Entegre", "Mevcut Heweso altyapısına oturur; ek operasyonel yük getirmez."],
  ];
  const cw = 5.83, gap = 0.35, ch = 1.7, y0 = 2.15, gy = 0.3;
  items.forEach((c, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = LM + col * (cw + gap), y = y0 + row * (ch + gy);
    s.addShape(p.ShapeType.roundRect, { x, y, w: cw, h: ch, rectRadius: 0.09, fill: { color: TINT }, line: { type: "none" }, shadow: shadow() });
    numCircle(s, x + 0.35, y + ch / 2 - 0.3, i + 1, 0.6);
    s.addText(c[0], { x: x + 1.2, y: y + 0.3, w: cw - 1.5, h: 0.45, fontFace: HSER, fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: x + 1.2, y: y + 0.78, w: cw - 1.5, h: 0.75, fontFace: BODY, fontSize: 13.5, color: INKTXT, lineSpacingMultiple: 1.05, margin: 0 });
  });
  s.addText("Otonom çalışır; tam görünürlük denetim panosu ile sağlanır.", { x: LM, y: 6.15, w: CW, h: 0.35, align: "center", fontFace: BODY, fontSize: 14, italic: true, color: MUTED, margin: 0 });
  s.addNotes("Teknik detay sona: güvenilirlik kanıtı olarak. AWS-native, ölçeklenebilir, güvenli, entegre. Jargon minimum.");
})();

// ── Slide 13 — Sonraki Adımlar (dark closing) ─────────────────────
(() => {
  const s = p.addSlide(); bgDark(s);
  title(s, "Kapanış", "Sonraki Adımlar", true);
  const steps = [
    ["Pilot kapsamı", "Seçili bir perakendeci segmentiyle başlıyoruz."],
    ["Başarı ölçütleri", "Marj, ciro ve tepki süresini birlikte tanımlıyoruz."],
    ["Değerlendirme", "30–60 gün sonunda sonuçları ölçüp yaygınlaştırma kararını veriyoruz."],
  ];
  const y0 = 2.05, rh = 1.05, gy = 0.28;
  steps.forEach((c, i) => {
    const y = y0 + i * (rh + gy);
    s.addShape(p.ShapeType.roundRect, { x: LM, y, w: 9.5, h: rh, rectRadius: 0.08, fill: { color: "1E3050" }, line: { type: "none" } });
    numCircle(s, LM + 0.32, y + rh / 2 - 0.3, i + 1, 0.6);
    s.addText(c[0], { x: LM + 1.2, y, w: 3.0, h: rh, valign: "middle", fontFace: HSER, fontSize: 18, bold: true, color: WHITE, margin: 0 });
    s.addText(c[1], { x: LM + 4.2, y, w: 5.1, h: rh, valign: "middle", fontFace: BODY, fontSize: 14.5, color: ICE, margin: 0 });
  });
  s.addShape(p.ShapeType.roundRect, { x: LM, y: 5.85, w: 12.1, h: 0.85, rectRadius: 0.1, fill: { color: ACCENT }, line: { type: "none" } });
  s.addText("Bir sonraki adım: pilot kapsamını birlikte belirleyelim.", { x: LM, y: 5.85, w: 12.1, h: 0.85, align: "center", valign: "middle", fontFace: HSER, fontSize: 19, bold: true, color: WHITE, margin: 0 });
  s.addNotes("Kapanış her zaman net bir istekle biter: pilot. Ölçütleri birlikte tanımlamak alıcıyı sürece ortak eder.");
})();

p.writeFile({ fileName: "Heweso_Satis_Sunumu.pptx" }).then(f => console.log("WROTE", f));
