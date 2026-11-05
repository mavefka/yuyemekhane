import requests
from bs4 import BeautifulSoup
import json
import urllib3
from datetime import datetime, timedelta
from urllib.parse import urljoin, unquote, urlparse
import re
import base64
import hashlib

# SSL sertifika uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MENU_URL = "https://menu.yalova.edu.tr/"
ANNOUNCEMENTS_URL = "https://yalova.edu.tr/tr/duyuru"

AYLAR = {
    "Ocak": "01", "Şubat": "02", "Mart": "03", "Nisan": "04",
    "Mayıs": "05", "Haziran": "06", "Temmuz": "07", "Ağustos": "08",
    "Eylül": "09", "Ekim": "10", "Kasım": "11", "Aralık": "12"
}

BINARY_EXTENSIONS = (
    '.pdf', '.xlsx', '.xls', '.doc', '.docx', '.ppt', '.pptx',
    '.zip', '.rar', '.jpg', '.jpeg', '.png', '.webp', '.gif'
)

ALLOWED_HTML_TAGS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li',
    'h2', 'h3', 'h4', 'h5', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'blockquote'
}


def detect_category(title, target_url):
    title_lower = title.lower()
    url_lower = target_url.lower()
    if "iskur" in url_lower or "işkur" in title_lower or "burs" in title_lower or "kariyer" in title_lower:
        return "Burs & Kariyer"
    if "arge." in url_lower or "bap." in url_lower or "tübitak" in title_lower or "tubitak" in title_lower or "proje" in title_lower:
        return "Proje & Ar-Ge"
    if "oidb." in url_lower or "yks" in title_lower or "ders" in title_lower or "kayıt" in title_lower or "akademik" in title_lower or "sınav" in title_lower:
        return "Öğrenci İşleri"
    if "sks." in url_lower or "topluluk" in title_lower or "yemek" in title_lower or "oryantasyon" in title_lower:
        return "SKS & Kampüs"
    return "Genel Duyuru"


def get_attachment_type(url):
    lower = url.lower().split('?')[0]
    if lower.endswith('.pdf'):
        return 'pdf'
    if lower.endswith(('.xlsx', '.xls', '.csv')):
        return 'excel'
    if lower.endswith(('.doc', '.docx')):
        return 'word'
    if lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
        return 'image'
    return 'link'


def format_attachment_label(a_tag, full_url):
    raw_text = a_tag.get_text(" ", strip=True)
    generic_words = {"tıklayınız", "tiklayiniz", "tıklayın", "buraya tıklayınız", "link", "bağlantı", "indir"}

    # Eğer link metni anlamlıysa ve "TIKLAYINIZ" gibi jenerik değilse doğrudan kullan
    if raw_text and raw_text.lower().strip(".:! ") not in generic_words and len(raw_text) > 3:
        return raw_text

    # Dosya adından anlamlı isim çıkar
    parsed_path = unquote(urlparse(full_url).path)
    filename = parsed_path.rstrip('/').split('/')[-1]
    if filename and '.' in filename:
        name_part, ext_part = filename.rsplit('.', 1)
        clean_name = name_part.replace('_', ' ').replace('-', ' ').strip()
        if clean_name:
            return f"{clean_name} ({ext_part.upper()})"

    # Üst elementin metninden bağlam çıkar
    parent = a_tag.find_parent(['p', 'li', 'div', 'td'])
    if parent:
        parent_text = parent.get_text(" ", strip=True)
        cleaned_parent = re.sub(r'(?i)\b(için\s+)?tıklayınız\.?\b', '', parent_text).strip(" :.-–—")
        if 3 < len(cleaned_parent) <= 90:
            return cleaned_parent

    return raw_text or "Bağlantıyı Aç"


def clean_announcement_html(content_div, base_url):
    if not content_div:
        return "", "", [], []

    soup_copy = BeautifulSoup(str(content_div), 'html.parser')
    root = soup_copy.find()
    if not root:
        return "", "", [], []

    # İstenmeyen etiketleri tamamen kaldır
    for bad in root.find_all(['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'meta', 'link']):
        bad.decompose()

    images = []
    for img in root.find_all('img'):
        src = img.get('src', '').strip()
        if src:
            full_img_url = urljoin(base_url, src)
            if full_img_url not in images and 'duyuru-img.png' not in full_img_url:
                images.append(full_img_url)
        img.decompose()

    attachments = []
    seen_urls = set()

    for a in root.find_all('a'):
        href = a.get('href', '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            a.unwrap()
            continue

        full_url = urljoin(base_url, href)
        label = format_attachment_label(a, full_url)
        att_type = get_attachment_type(full_url)

        if full_url not in seen_urls:
            seen_urls.add(full_url)
            attachments.append({
                "label": label,
                "url": full_url,
                "type": att_type
            })

        a.attrs = {
            'href': full_url,
            'target': '_blank',
            'rel': 'noopener noreferrer'
        }

    # İzin verilmeyen etiketleri unwrap et, izin verilenlerin tüm inline style/class niteliklerini temizle
    for tag in list(root.find_all(True)):
        if tag.name not in ALLOWED_HTML_TAGS:
            tag.unwrap()
        elif tag.name != 'a':
            tag.attrs = {}

    # İç içe geçmiş <p> etiketlerini düzelt
    for p in list(root.find_all('p')):
        if p.find('p'):
            p.unwrap()

    # Boş paragrafları temizle
    for p in list(root.find_all(['p', 'div', 'h2', 'h3', 'h4', 'h5'])):
        if not p.get_text(strip=True) and not p.find('br'):
            p.decompose()

    plain_text = re.sub(r'\s+', ' ', root.get_text(" ", strip=True)).strip()
    plain_text = plain_text.replace('**', '')
    if plain_text.startswith('iŞKUR'):
        plain_text = 'İŞKUR' + plain_text[5:]

    if len(plain_text) < 35 and attachments:
        summary = f"Bu duyuruya ait {len(attachments)} adet ek dosya veya bağlantıyı görüntülemek için tıklayınız."
    else:
        summary = plain_text[:170].rsplit(' ', 1)[0] + "..." if len(plain_text) > 170 else plain_text

    inner_html = "".join(str(child) for child in root.children).strip()
    inner_html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', inner_html)
    inner_html = inner_html.replace('iŞKUR', 'İŞKUR')
    return inner_html, summary, attachments, images


def fetch_announcements(session):
    print("Üniversite duyuruları çekiliyor...")
    announcements = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        resp = session.get(ANNOUNCEMENTS_URL, headers=headers, verify=False, timeout=15)
        resp.encoding = 'utf-8'
        if resp.status_code != 200:
            print(f"Duyuru sayfası yanıt vermedi: HTTP {resp.status_code}")
            return announcements

        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.gdlr-core-event-item-list')

        for item in items[:10]:
            a_tag = item.select_one('h3.gdlr-core-event-item-title a')
            if not a_tag or not a_tag.get('href'):
                continue

            title = a_tag.get_text(" ", strip=True)
            original_url = urljoin(ANNOUNCEMENTS_URL, a_tag['href'].strip())

            date_el = item.select_one('.gdlr-core-blog-info-date')
            date_str = date_el.get_text(" ", strip=True) if date_el else ""

            target_url = original_url
            content_div = None

            try:
                detail_resp = session.get(original_url, headers=headers, verify=False, timeout=12)
                detail_resp.encoding = 'utf-8'
                detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
                content_div = detail_soup.select_one('.gdlr-core-blog-content')

                if content_div:
                    raw_text = content_div.get_text(" ", strip=True)
                    raw_links = [
                        urljoin(original_url, la['href'].strip())
                        for la in content_div.find_all('a', href=True)
                        if not la['href'].strip().startswith(('#', 'javascript:'))
                    ]

                    # Eğer ana duyuru sayfası sadece alt birime yönlendiren kısa bir "Duyuru İçin TIKLAYINIZ" sayfasıysa takip et
                    if (
                        len(raw_text) < 120
                        and len(raw_links) == 1
                        and 'yalova.edu.tr' in raw_links[0].lower()
                        and not raw_links[0].lower().split('?')[0].endswith(BINARY_EXTENSIONS)
                    ):
                        sub_url = raw_links[0]
                        sub_resp = session.get(sub_url, headers=headers, verify=False, timeout=12)
                        sub_resp.encoding = 'utf-8'
                        sub_soup = BeautifulSoup(sub_resp.text, 'html.parser')
                        sub_content = sub_soup.select_one('.gdlr-core-blog-content')
                        if sub_content and len(sub_content.get_text(" ", strip=True)) >= len(raw_text):
                            content_div = sub_content
                            target_url = sub_url
            except Exception as e:
                print(f"Duyuru detayı çekilemedi ({title[:40]}): {e}")

            content_html, summary, attachments, images = clean_announcement_html(content_div, target_url)
            category = detect_category(title, target_url)

            announcements.append({
                "title": title,
                "date": date_str,
                "category": category,
                "url": target_url,
                "original_url": original_url,
                "summary": summary or title,
                "content_html": content_html,
                "attachments": attachments,
                "images": images
            })
            print(f"  + Duyuru eklendi: {title[:55]} ({category})")

    except Exception as e:
        print(f"Duyurular çekilirken hata oluştu: {e}")

    return announcements


def fetch_and_combine_menus():
    session = requests.Session()
    print("Siteye bağlanılıyor ve tarih bilgileri ayarlanıyor...")

    now = datetime.now()
    # Çekilecek hedefler listesi: Önce bulunduğumuz ay
    hedef_tarihler = [
        (str(now.year), str(now.month))
    ]

    # Sonraki ayı da listeye ekle (Eğer Aralık ayındaysak sonraki yılın Ocağına geçer)
    if now.month == 12:
        hedef_tarihler.append((str(now.year + 1), "1"))
    else:
        hedef_tarihler.append((str(now.year), str(now.month + 1)))

    def get_menu_for_meal(meal_code, target_year, target_month):
        print(f"Veri Çekiliyor -> Yıl: {target_year}, Ay: {target_month}, Öğün Kodu: {meal_code}")
        data = {
            "Yil": target_year,
            "Ay": target_month,
            "Ogun": meal_code
        }

        meal_data = {}
        try:
            response = session.post(MENU_URL, data=data, verify=False, timeout=15)
            response.encoding = 'utf-8'
            msoup = BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"Menü sayfası çekilemedi ({target_year}-{target_month}, Öğün {meal_code}): {e}")
            return meal_data

        home_table = msoup.find('ul', class_='home-table')

        if not home_table:
            return meal_data

        gunler = home_table.find_all('li', recursive=False)

        for gun in gunler:
            span_tarih = gun.find('span')
            if not span_tarih:
                continue

            raw_tarih = span_tarih.text.strip().split()
            if len(raw_tarih) < 3:
                continue

            gun_no = raw_tarih[0].zfill(2)
            ay_isim = raw_tarih[1]
            yil_degeri = raw_tarih[2]

            ay_no = AYLAR.get(ay_isim, "01")
            formatted_date = f"{yil_degeri}-{ay_no}-{gun_no}"

            yemekler_listesi = []
            before_bg = gun.find('div', class_='before-bg')

            if before_bg:
                yemek_satirlari = before_bg.find('ul').find_all('li', recursive=False)
                for satir in yemek_satirlari:
                    if 'text-right' in satir.get('class', []):
                        continue

                    raw_text = satir.text.strip()
                    if not raw_text:
                        continue

                    try:
                        isim_kism_ayri = raw_text.rsplit('(', 1)
                        isim = isim_kism_ayri[0].strip()
                        kalori = int(isim_kism_ayri[1].replace('Cal)', '').strip())

                        # İçindekiler kısmı (Tooltip)
                        icindekiler = ""
                        if satir.has_attr('data-original-title'):
                            raw_title = satir['data-original-title']
                            clean_title = re.sub(r'<[^>]+>', '', raw_title)
                            icindekiler = clean_title.replace('İÇİNDEKİLER:', '').strip()

                        yemekler_listesi.append({
                            "name": isim,
                            "cal": kalori,
                            "ingredients": icindekiler
                        })
                    except Exception:
                        pass

            meal_data[formatted_date] = yemekler_listesi

        return meal_data

    combined_database = {}

    # Hem bu ayı hem sonraki ayı sırayla çekip ana veritabanında birleştiriyoruz
    for yil, ay in hedef_tarihler:
        ogle_verisi = get_menu_for_meal("1", yil, ay)
        aksam_verisi = get_menu_for_meal("2", yil, ay)

        all_dates = set(ogle_verisi.keys()).union(set(aksam_verisi.keys()))

        for date in all_dates:
            combined_database[date] = {
                "ogle": ogle_verisi.get(date, []),
                "aksam": aksam_verisi.get(date, [])
            }

    # Üniversite duyurularını çek
    announcements_list = fetch_announcements(session)

    # Mevcut veri.json dosyasını oku (eski menü, duyuru ve arşivlenmiş yorumları korumak için)
    old_data = {}
    try:
        with open('veri.json', 'r', encoding='utf-8') as old_f:
            old_data = json.load(old_f)
    except Exception:
        old_data = {}

    if not combined_database and isinstance(old_data.get('menus'), dict):
        combined_database = old_data.get('menus', {})

    if not announcements_list:
        announcements_list = old_data.get('announcements', [])

    # Yorumları senkronize et ve kalıcı olarak arşivle (geçmiş 7 gün + gelecek 14 gün)
    raw_archive = old_data.get('comments', {}) if isinstance(old_data.get('comments'), dict) else {}
    now_dt = datetime.now()
    now_ms = int(now_dt.timestamp() * 1000)
    valid_retention_dates = {(now_dt + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-14, 16)}

    # 14 günden eski yorum anahtarlarını temizle (veri.json şişmesini önler)
    comments_archive = {
        k: v for k, v in raw_archive.items()
        if isinstance(k, str) and len(k) >= 10 and k[:10] in valid_retention_dates and isinstance(v, list)
    }

    # ECDSA P-256 (secp256r1) Yönetici İmza Doğrulayıcı (Sıfır ek paket, saf Python)
    P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
    P256_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
    P256_A = P256_P - 3
    P256_G = (
        0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
        0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5
    )
    P256_Q = (
        int.from_bytes(base64.urlsafe_b64decode('3ga6Y33aSC2Umxrb7jkts7vTnavw8SuScP_MQa2P708='), 'big'),
        int.from_bytes(base64.urlsafe_b64decode('xhScBPA2HRfkakF_ogre4OtptGkZKwYb54N5sqK5fdQ='), 'big')
    )

    def ec_pt_add(p1, p2):
        if p1 is None:
            return p2
        if p2 is None:
            return p1
        x1, y1 = p1
        x2, y2 = p2
        if x1 == x2 and (y1 + y2) % P256_P == 0:
            return None
        if p1 == p2:
            lam = ((3 * x1 * x1 + P256_A) * pow(2 * y1, -1, P256_P)) % P256_P
        else:
            lam = ((y2 - y1) * pow(x2 - x1, -1, P256_P)) % P256_P
        x3 = (lam * lam - x1 - x2) % P256_P
        return (x3, (lam * (x1 - x3) - y1) % P256_P)

    def ec_pt_mul(k, pt):
        res = None
        addend = pt
        while k:
            if k & 1:
                res = ec_pt_add(res, addend)
            addend = ec_pt_add(addend, addend)
            k >>= 1
        return res

    def verify_admin_sig(msg_str, sig_b64):
        if not sig_b64 or not isinstance(sig_b64, str):
            return False
        try:
            raw = base64.b64decode(sig_b64)
            if len(raw) != 64:
                return False
            r = int.from_bytes(raw[:32], 'big')
            s = int.from_bytes(raw[32:], 'big')
            if not (1 <= r < P256_N and 1 <= s < P256_N):
                return False
            z = int.from_bytes(hashlib.sha256(msg_str.encode('utf-8')).digest(), 'big')
            w = pow(s, -1, P256_N)
            pt = ec_pt_add(ec_pt_mul((z * w) % P256_N, P256_G), ec_pt_mul((r * w) % P256_N, P256_Q))
            return pt is not None and (pt[0] % P256_N) == r
        except Exception:
            return False

    def detect_valid_image_mime(raw_bytes):
        if not raw_bytes or len(raw_bytes) > 75000:
            return None
        if len(raw_bytes) >= 12 and raw_bytes[:4] == b'RIFF' and raw_bytes[8:12] == b'WEBP':
            return 'image/webp'
        if raw_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if raw_bytes.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        return None

    target_comment_dates = [(now_dt + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-7, 15)]

    for c_date in target_comment_dates:
        for meal_key in ("ogle", "aksam"):
            slot_key = f"{c_date}_{meal_key}"
            topic = f"yuyemekhane_c_{c_date.replace('-', '_')}_{meal_key}"
            existing_list = [item for item in comments_archive.get(slot_key, []) if isinstance(item, dict) and item.get("sig")]
            seen_ids = {str(item.get("id")) for item in existing_list if item.get("id")}
            seen_content = {
                f"{str(item.get('author', '')).lower()}|{str(item.get('text', '')).lower()}"
                for item in existing_list
            }
            author_counts = {}
            for item in existing_list:
                a_key = str(item.get("author", "")).strip().lower()
                author_counts[a_key] = author_counts.get(a_key, 0) + 1
            deleted_ids = set()

            try:
                resp = session.get(f"https://ntfy.sh/{topic}/json?poll=1&since=all", timeout=6)
                if resp.status_code == 200 and resp.text.strip():
                    for line in resp.text.strip().splitlines():
                        try:
                            ev = json.loads(line)
                            if ev.get("event") != "message":
                                continue
                            msg_raw = ev.get("message", "")
                            if not isinstance(msg_raw, str) or len(msg_raw) > 95000:
                                continue
                            c_obj = json.loads(msg_raw)
                            if not isinstance(c_obj, dict):
                                continue

                            # Yönetici yorum silme komutu
                            if c_obj.get("action") == "delete" and c_obj.get("targetId") and c_obj.get("sig"):
                                target_id = str(c_obj.get("targetId"))
                                if verify_admin_sig(f"DELETE|{slot_key}|{target_id}", c_obj.get("sig")):
                                    deleted_ids.add(target_id)
                                continue

                            c_id = str(c_obj.get("id") or ev.get("id") or "").strip()[:64]
                            if not c_id or c_id in seen_ids:
                                continue

                            sig_val = str(c_obj.get("sig") or "").strip()
                            if not sig_val:
                                continue

                            author = re.sub(r'[\x00-\x1f\x7f]', '', str(c_obj.get("author") or "")).strip()[:28]
                            if len(author) < 2:
                                continue

                            author_key = author.lower()
                            if author_counts.get(author_key, 0) >= 4:
                                continue

                            text = re.sub(r'[\x00-\x1f\x7f]', '', str(c_obj.get("text") or "")).strip()[:240]

                            # Puan doğrulaması (1-5 arası tam sayı)
                            clean_rating = None
                            try:
                                r_val = int(round(float(c_obj.get("rating"))))
                                if 1 <= r_val <= 5:
                                    clean_rating = r_val
                            except Exception:
                                clean_rating = None

                            # Yönetici ECDSA imza doğrulaması (onaysız hiçbir yorum arşive giremez)
                            approval_payload = f"APPROVE|{slot_key}|{c_id}|{author}|{clean_rating or ''}|{text}"
                            if not verify_admin_sig(approval_payload, sig_val):
                                continue

                            # Görsel doğrulaması (Magic-byte + boyut kontrolü)
                            clean_img = ""
                            img_val = c_obj.get("img", "")
                            if isinstance(img_val, str):
                                if re.match(r'^https://ntfy\.sh/file/[A-Za-z0-9_-]+(\.[A-Za-z0-9]+)?$', img_val):
                                    try:
                                        img_resp = session.get(img_val, timeout=6)
                                        if img_resp.status_code == 200:
                                            mime = detect_valid_image_mime(img_resp.content)
                                            if mime:
                                                b64_str = base64.b64encode(img_resp.content).decode('ascii')
                                                clean_img = f"data:{mime};base64,{b64_str}"
                                    except Exception:
                                        clean_img = ""
                                elif re.match(r'^data:image/(webp|png|jpeg);base64,[A-Za-z0-9+/=]+$', img_val) and len(img_val) <= 95000:
                                    try:
                                        b64_part = img_val.split(',', 1)[1]
                                        raw_bytes = base64.b64decode(b64_part, validate=True)
                                        mime = detect_valid_image_mime(raw_bytes)
                                        if mime:
                                            clean_img = img_val
                                    except Exception:
                                        clean_img = ""

                            if not text and not clean_img:
                                continue

                            content_sig = f"{author_key}|{text.lower()}"
                            if content_sig in seen_content:
                                continue

                            try:
                                raw_ts = int(float(c_obj.get("ts", now_ms)))
                                if raw_ts < now_ms - 45 * 86400000 or raw_ts > now_ms + 600000:
                                    clean_ts = now_ms
                                else:
                                    clean_ts = raw_ts
                            except Exception:
                                clean_ts = now_ms

                            raw_time = str(c_obj.get("time") or "").strip()
                            clean_time = raw_time if re.match(r'^\d{2}:\d{2}$', raw_time) else now_dt.strftime("%H:%M")

                            sanitized_entry = {
                                "id": c_id,
                                "author": author,
                                "rating": clean_rating,
                                "text": text,
                                "img": clean_img,
                                "time": clean_time,
                                "ts": clean_ts,
                                "sig": sig_val
                            }

                            existing_list.append(sanitized_entry)
                            seen_ids.add(c_id)
                            seen_content.add(content_sig)
                            author_counts[author_key] = author_counts.get(author_key, 0) + 1
                        except Exception:
                            continue
            except Exception:
                pass

            if deleted_ids:
                existing_list = [it for it in existing_list if str(it.get("id")) not in deleted_ids]

            if existing_list:
                existing_list.sort(key=lambda x: x.get("ts", 0))
                comments_archive[slot_key] = existing_list[-50:]
            elif slot_key in comments_archive:
                del comments_archive[slot_key]

    guncel_zaman = datetime.now().strftime("%d.%m.%Y")

    final_output = {
        "last_updated": guncel_zaman,
        "menus": combined_database,
        "announcements": announcements_list,
        "comments": comments_archive
    }

    with open('veri.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)

    with open('veri.js', 'w', encoding='utf-8') as f_js:
        f_js.write("window.__VERI_DATA__ = ")
        json.dump(final_output, f_js, ensure_ascii=False)
        f_js.write(";\n")

    print(f"\nTüm veriler başarıyla çekildi! Toplam gün: {len(combined_database)}, Duyuru: {len(announcements_list)} (Son Güncelleme: {guncel_zaman})")


if __name__ == "__main__":
    fetch_and_combine_menus()
