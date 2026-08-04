const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa6");

// ── icon rendering (white glyph → transparent PNG) ────────────────
const ICONMAP = {
  userTie:FA.FaUserTie, gauge:FA.FaGaugeHigh, chartLine:FA.FaChartLine, database:FA.FaDatabase,
  clock:FA.FaRegClock, bolt:FA.FaBolt, search:FA.FaMagnifyingGlass, branch:FA.FaCodeBranch,
  store:FA.FaStore, brain:FA.FaBrain, tools:FA.FaScrewdriverWrench, calc:FA.FaCalculator,
  upload:FA.FaCloudArrowUp, filter:FA.FaFilter, layers:FA.FaLayerGroup, searchChart:FA.FaMagnifyingGlassChart,
  cubes:FA.FaCubes, fileLines:FA.FaFileLines, robot:FA.FaRobot, envelope:FA.FaEnvelope,
  server:FA.FaServer, trendUp:FA.FaArrowTrendUp,
};
async function renderIcon(Comp){
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#FFFFFF", size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256,256,{fit:"contain",background:{r:0,g:0,b:0,alpha:0}}).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const ICON = {};
  for (const [k, Comp] of Object.entries(ICONMAP)) ICON[k] = await renderIcon(Comp);

  const p = new pptxgen();
  p.defineLayout({ name: "DIAG", width: 13.33, height: 9.0 });
  p.layout = "DIAG";
  const s = p.addSlide();
  s.background = { color: "FFFFFF" };

  const NAVY="1E2761", GREEN="2C6E49", TEAL="028090", ORANGE="C05621", MAROON="7B241C";
  const DB="3F51B5", LAMBDA="ED7D31", AI="7B2FBE", S3G="2E7D32", ATH="8E44AD",
        SES="00838F", PINK="D6336C", SLATE="455A64", GRAY="5A6B85", DBT="C0392B";
  const OK="1E8E5A", BAD="C0392B", INK="1B2A44", MUTED="5A6B85";
  const HSER="Cambria", BODY="Calibri";
  const NW=1.35, IC=0.52, ISZ=0.3;
  const COL=[1.03, 2.72, 4.22, 6.12, 7.78, 9.22, 10.66, 12.10];
  const sh=()=>({type:"outer",color:"AEB8CC",blur:4,offset:2,angle:90,opacity:0.32});

  function node(cx, topY, ic, icon, t, sub){
    s.addShape(p.ShapeType.roundRect,{x:cx-IC/2,y:topY,w:IC,h:IC,rectRadius:0.07,fill:{color:ic},line:{type:"none"},shadow:sh()});
    s.addImage({ data: ICON[icon], x: cx-ISZ/2, y: topY+(IC-ISZ)/2, w: ISZ, h: ISZ });
    s.addText(t,{x:cx-NW/2,y:topY+IC+0.04,w:NW,h:0.26,align:"center",fontFace:BODY,fontSize:10,bold:true,color:INK,margin:0});
    s.addText(sub,{x:cx-NW/2,y:topY+IC+0.29,w:NW,h:0.34,align:"center",fontFace:BODY,fontSize:8,italic:true,color:MUTED,lineSpacingMultiple:0.9,margin:0});
  }
  function arrow(cxA, cxB, y, label){
    const x1=cxA+IC/2+0.03, x2=cxB-IC/2-0.03;
    s.addShape(p.ShapeType.line,{x:x1,y:y,w:x2-x1,h:0,line:{color:GRAY,width:1.5,endArrowType:"triangle"}});
    if(label) s.addText(label,{x:x1-0.1,y:y-0.28,w:(x2-x1)+0.2,h:0.24,align:"center",fontFace:BODY,fontSize:7.5,italic:true,color:GRAY,margin:0});
  }

  // title bar
  s.addShape(p.ShapeType.rect,{x:0,y:0,w:13.33,h:0.72,fill:{color:NAVY},line:{type:"none"}});
  s.addText("Akıllı Fiyatlandırma Ajanı  —  Uçtan Uca Sistem Akışı",{x:0.2,y:0,w:9.3,h:0.72,valign:"middle",fontFace:HSER,fontSize:21,bold:true,color:"FFFFFF",charSpacing:1,margin:0});
  s.addText("FastAPI · AWS eu-central-1 · Bedrock Nova Lite",{x:9.4,y:0,w:3.75,h:0.72,valign:"middle",align:"right",fontFace:BODY,fontSize:11,italic:true,color:"CADCFC",margin:0});

  // lane header
  const lanes=[["ACTORS",0.12,1.95,NAVY],["UYGULAMA & VERİ",1.95,5.35,GREEN],["TETİKLEME",5.35,6.9,TEAL],["AWS BULUT SERVİSLERİ  ·  eu-central-1",6.9,13.21,ORANGE]];
  lanes.forEach(([t,x0,x1,c])=>{
    s.addShape(p.ShapeType.rect,{x:x0,y:0.78,w:x1-x0,h:0.4,fill:{color:c},line:{color:"FFFFFF",width:1.5}});
    s.addText(t,{x:x0,y:0.78,w:x1-x0,h:0.4,align:"center",valign:"middle",fontFace:BODY,fontSize:11,bold:true,color:"FFFFFF",charSpacing:1,margin:0});
  });

  const bandY=[1.28,2.80,4.32,5.84,7.36];
  function loopBand(i,color,text){
    const y=bandY[i];
    s.addShape(p.ShapeType.rect,{x:0.12,y:y,w:13.09,h:1.46,fill:{color:(i%2?"F4F7FB":"FAFBFE")},line:{type:"none"}});
    s.addShape(p.ShapeType.rect,{x:0.12,y:y,w:13.09,h:0.32,fill:{color:color},line:{type:"none"}});
    s.addShape(p.ShapeType.ellipse,{x:0.24,y:y+0.045,w:0.23,h:0.23,fill:{color:"FFFFFF"},line:{type:"none"}});
    s.addText(String(i+1),{x:0.24,y:y+0.045,w:0.23,h:0.23,align:"center",valign:"middle",fontFace:BODY,fontSize:11,bold:true,color:color,margin:0});
    s.addText(text,{x:0.6,y:y,w:12.5,h:0.32,valign:"middle",fontFace:BODY,fontSize:11,bold:true,color:"FFFFFF",charSpacing:0.5,margin:0});
    return y+0.42;
  }

  // LOOP 1
  let ty=loopBand(0,NAVY,"LOOP 1 · KURULUM & İZLEME — Yönetici kataloğu ve fiyatları panelden yönetir");
  node(COL[0],ty,NAVY,"userTie","Yönetici","admin");
  node(COL[1],ty,GREEN,"gauge","Dashboard","FastAPI · SSE");
  node(COL[2],ty,GREEN,"chartLine","Simülasyon","satış + rakip");
  node(COL[4],ty,DB,"database","DynamoDB","4 tablo · kaynak");
  let ay=ty+IC/2;
  arrow(COL[0],COL[1],ay,"paneli açar"); arrow(COL[1],COL[2],ay,"üretir"); arrow(COL[2],COL[4],ay,"REST · yazar");

  // LOOP 2
  ty=loopBand(1,TEAL,"LOOP 2 · TETİKLEME — EventBridge ajanı her dakika çağırır  (varsayılan KAPALI · maliyet koruması)");
  node(COL[3],ty,PINK,"clock","EventBridge","rate(1 dk)");
  node(COL[4],ty,LAMBDA,"bolt","Lambda","pricing-agent");
  node(COL[5],ty,DB,"search","query_sales","60 dk kontrol");
  node(COL[6],ty,GRAY,"branch","Karar","sağlıklı=atla");
  ay=ty+IC/2;
  arrow(COL[3],COL[4],ay,"çağırır"); arrow(COL[4],COL[5],ay,"tarar"); arrow(COL[5],COL[6],ay,"kritik → LOOP 3");

  // LOOP 3 + branch
  ty=loopBand(2,GREEN,"LOOP 3 · AJAN KARARI — Bedrock ReAct döngüsü · 14 araç  (algı → muhakeme → aksiyon)");
  node(COL[0],ty,NAVY,"store","Pazar","satış & rakip");
  node(COL[4],ty,AI,"brain","Bedrock","Nova Lite · ReAct");
  node(COL[5],ty,TEAL,"tools","14 Araç","trend · rakip · zaman");
  node(COL[6],ty,AI,"calc","decide_price","matematik Python'da");
  ay=ty+IC/2;
  arrow(COL[0],COL[4],ay,"tetikler"); arrow(COL[4],COL[5],ay,"muhakeme"); arrow(COL[5],COL[6],ay,"seçer");
  const bx=COL[7]-0.85, bw=1.7;
  s.addShape(p.ShapeType.roundRect,{x:bx,y:ty-0.02,w:bw,h:0.5,rectRadius:0.06,fill:{color:OK},line:{type:"none"},shadow:sh()});
  s.addText("✓ GÜNCELLE",{x:bx,y:ty-0.02,w:bw,h:0.28,align:"center",valign:"middle",fontFace:BODY,fontSize:9.5,bold:true,color:"FFFFFF",margin:0});
  s.addText("update_price → log + SES",{x:bx,y:ty+0.23,w:bw,h:0.24,align:"center",fontFace:BODY,fontSize:7,italic:true,color:"EAF7F0",margin:0});
  s.addShape(p.ShapeType.roundRect,{x:bx,y:ty+0.6,w:bw,h:0.5,rectRadius:0.06,fill:{color:BAD},line:{type:"none"},shadow:sh()});
  s.addText("✗ ESCALATE",{x:bx,y:ty+0.6,w:bw,h:0.28,align:"center",valign:"middle",fontFace:BODY,fontSize:9.5,bold:true,color:"FFFFFF",margin:0});
  s.addText("insana devret · e-posta",{x:bx,y:ty+0.85,w:bw,h:0.24,align:"center",fontFace:BODY,fontSize:7,italic:true,color:"FBEAEA",margin:0});
  s.addShape(p.ShapeType.line,{x:COL[6]+IC/2+0.03,y:ay-0.05,w:(bx-0.03)-(COL[6]+IC/2+0.03),h:-0.05,line:{color:OK,width:1.5,endArrowType:"triangle"}});
  s.addShape(p.ShapeType.line,{x:COL[6]+IC/2+0.03,y:ay+0.05,w:(bx-0.03)-(COL[6]+IC/2+0.03),h:0.75,line:{color:BAD,width:1.5,endArrowType:"triangle"}});

  // LOOP 4
  ty=loopBand(3,ORANGE,"LOOP 4 · VERİ HATTI — Medallion Bronze→Silver→Gold  (saatlik, Lambda içinde) + dbt");
  node(COL[0],ty,DB,"database","DynamoDB","kaynak");
  node(COL[3],ty,DBT,"cubes","dbt","izole şema · manuel");
  node(COL[4],ty,LAMBDA,"upload","export_to_s3","Bronze · ham");
  node(COL[5],ty,LAMBDA,"filter","silver.py","temiz + join");
  node(COL[6],ty,LAMBDA,"layers","gold.py","aggregate");
  node(COL[7],ty,S3G,"searchChart","S3 + Athena","Hive · Glue");
  ay=ty+IC/2;
  arrow(COL[0],COL[4],ay,"export"); arrow(COL[4],COL[5],ay,"dönüştür"); arrow(COL[5],COL[6],ay,"aggregate"); arrow(COL[6],COL[7],ay,"yazar");
  s.addText("Not: araçlar Athena'dan Silver'ı sorgular · dbt, Silver/Gold'u izole şemada (heweso_analytics_dbt) yeniden üretir.",{x:2.15,y:ty+0.02,w:3.05,h:0.98,valign:"middle",fontFace:BODY,fontSize:8,italic:true,color:MUTED,lineSpacingMultiple:1.0,margin:0});

  // LOOP 5
  ty=loopBand(4,MAROON,"LOOP 5 · HAFTALIK ANALİTİK & ÖĞRENME — rapor + epsilon-greedy uyarlama");
  node(COL[0],ty,NAVY,"userTie","Yönetici","raporu alır");
  node(COL[1],ty,SLATE,"server","MCP server","14 araç · yerel");
  node(COL[2],ty,GREEN,"trendUp","Öğrenme","bundle oranları ↑");
  node(COL[3],ty,PINK,"clock","EventBridge","haftalık cron");
  node(COL[4],ty,LAMBDA,"bolt","Analytics λ","reporter");
  node(COL[5],ty,ATH,"fileLines","Rapor üret","Gold sorgular");
  node(COL[6],ty,AI,"robot","report_agent","Bedrock yorumlar");
  node(COL[7],ty,SES,"envelope","SES","→ yöneticiye");
  ay=ty+IC/2;
  arrow(COL[3],COL[4],ay,"çağırır"); arrow(COL[4],COL[5],ay,"üretir"); arrow(COL[5],COL[6],ay,"yorum"); arrow(COL[6],COL[7],ay,"gönderir");

  await p.writeFile({fileName:"Heweso_Sistem_Akisi.pptx"});
  console.log("WROTE ok");
})();
