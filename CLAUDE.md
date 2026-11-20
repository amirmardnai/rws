# RWS Project & Railway Deployment Runbook (راهنمای اختصاصی ریلوی)

پروژه **RWS (Real-Time Web Stream & Ingress Engine)** یک سرویس مخابراتی پرسرعت، ضد بن و بدون قطعی مبتنی بر معماری استریم چندگانه (XHTTP + WebSocket) برای استقرار روی PaaS (ریلوی) است.

---

## ۱. معماری و اصول ضد بن ریلوی (Railway Anti-Abuse)

1. **پورت ورودی ۸۰۰۰ (Nginx Front-Door):**
   - در تنظیمات ریلوی (**Settings -> Networking -> Generate Domain**)، همیشه گزینه `+ Custom port` انتخاب و عدد **`8000`** وارد شود.
   - پورت ۸۰۰۰ پورت اصلی Nginx است که ترافیک عمومی را تحویل گرفته و به پورت‌های مخفی داخلی هدایت می‌کند:
     - `/api/v1/telemetry` -> XHTTP (18081)
     - `/api/v1/live` -> WS (18080)
     - `/api.cluster.v1` -> gRPC (18083)
     - `/api/v1/stream` -> HTTPUpgrade (18084)
     - `/panel/*` و `/` -> سوپروایزر پایتون (5000)

2. **استتار کامل پروسه‌ها و لاگ‌ها:**
   - باینری هسته با نام `rws-core` اجرا می‌شود (نه `xray`).
   - در لاگ‌های کانتینر **هیچ لینک `vless://` نباید چاپ شود** تا اسکنر رجکس ریلوی پروژه را مسدود نکند.
   - لینک‌ها و فایل‌های کلاینت در پرتال امن به آدرس `https://<DOMAIN>/panel/portal?key=8282` قرار دارند.

---

## ۲. اتصال از داخل ایران و دور زدن فیلترینگ دامنه‌های ریلوی

1. **مشکل جعل DNS (DNS Poisoning):**
   - دامنه‌های `*.up.railway.app` در ایران به `127.135.0.*` سیاهچاله می‌شوند.
   - رنج آی‌پی اصلی ریلوی (`50.7.*.*`) نیز فیلتر و تایم‌اوت است.

2. **آی‌پی تمیز فعال و تست‌شده:**
   - **آدرس آی‌پی تمیز:** `153.52.255.81`
   - اتصال به آی‌پی `153.52.255.81` روی پورت ۴۴۳ همراه با ارسال `Host` و `SNI` دامنه‌ی ریلوی شما، ترافیک را بدون فیلتر و با بالاترین سرعت مستقیماً برقرار می‌کند.

3. **فرمت کانفیگ‌های فعال (VLESS):**
   - **وب‌سوکت پرسرعت:**
     `vless://90cd4a77-141a-43c9-991b-08263cfe9c10@153.52.255.81:443?encryption=none&security=tls&sni=<YOUR_DOMAIN>&fp=chrome&type=ws&host=<YOUR_DOMAIN>&path=%2Fapi%2Fv1%2Flive#OmniMesh-WS-CleanIP`
   - **پایدارترین با فرگمنت (ضد قطعی):**
     `vless://90cd4a77-141a-43c9-991b-08263cfe9c10@153.52.255.81:443?encryption=none&security=tls&sni=<YOUR_DOMAIN>&fp=chrome&alpn=http%2F1.1&fm=%7B%22tcp%22%3A%5B%7B%22type%22%3A%22fragment%22%2C%22settings%22%3A%7B%22packets%22%3A%221-3%22%2C%22lengths%22%3A%5B%2248-96%22%5D%2C%22delays%22%3A%5B%222-5%22%5D%2C%22maxSplit%22%3A%224-8%22%7D%7D%5D%7D&type=ws&host=<YOUR_DOMAIN>&path=%2Fapi%2Fv1%2Flive#RWS-WS-Frag`

---

## ۳. متغیرهای ریلوی (Variables Raw Editor)

```env
PORT=8000
ADMIN_PASSWORD=8282
ADMIN_PATH=panel
UUID=90cd4a77-141a-43c9-991b-08263cfe9c10
PUBLIC_HOST=rws-production-xxxx.up.railway.app
XHTTP_PATH=/api/v1/telemetry
WS_PATH=/api/v1/live
GRPC_SERVICE=api.cluster.v1
HU_PATH=/api/v1/stream
CLEAN_IPS=153.52.255.81,104.18.138.193,104.18.202.232,172.64.155.209,104.17.70.206
```

---

## ۴. موتور ساخت کانفیگ برمودا (Bermuda Portal v4.0 Integration)

پروژه به صورت بومی از ساختار تولید کانفیگ **BERMUDA.PORTAL.V4.html** پشتیبانی می‌کند:

1. **پروتکل فرگمنت `&fm=` (برای هسته Xray، v2rayN، v2rayNG و PattNG):**
   قواعد تکه‌تکه کردن پکت‌های L4 را مستقیم داخل رشته VLESS بدون نیاز به فایل JSON جداگانه انکود می‌کند:
   - **`PKT-1-3-VERIFIED` (پرچمدار تست‌شده در ایران):**
     `packets: "1-3"`, `lengths: ["48-96"]`, `delays: ["2-5"]`, `maxSplit: "4-8"`, `alpn: "http/1.1"`
   - **`CASCADED-DEEP` (مخصوص خطوط همراه اول و ایرانسل با اختلال شدید):**
     `packets: "1-3"`, `lengths: ["16-64"]`, `delays: ["3-7"]`, `maxSplit: "4-8"`

2. **پروتکل فرگمنت آیفون `&fragment=` (مخصوص Happ، Streisand، V2Box):**
   `&fragment=48-96%2C2-5%2C1-3`

3. **لیست آی‌پی‌های تمیز طلایی (Golden Anycast Presets):**
   - `153.52.255.81` (لبه Anycast اختصاصی تایید شده برای PaaS در ایران)
   - `104.18.138.193` (لبه طلایی کلودفلر با پینگ پایین)
   - `104.18.202.232` (آی‌پی سازمانی وایت‌لیست Speedtest)
   - `172.64.155.209` (آی‌پی سازمانی ChatGPT ضد شکن)

