import requests
from bs4 import BeautifulSoup
import json
import urllib3
from datetime import datetime
import re

# SSL sertifika uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://menu.yalova.edu.tr/"

AYLAR = {
    "Ocak": "01", "Şubat": "02", "Mart": "03", "Nisan": "04",
    "Mayıs": "05", "Haziran": "06", "Temmuz": "07", "Ağustos": "08",
    "Eylül": "09", "Ekim": "10", "Kasım": "11", "Aralık": "12"
}

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
        
        response = session.post(URL, data=data, verify=False)
        response.encoding = 'utf-8'
        msoup = BeautifulSoup(response.text, 'html.parser')
        
        meal_data = {}
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
            
    guncel_zaman = datetime.now().strftime("%d.%m.%Y")
    
    final_output = {
        "last_updated": guncel_zaman,
        "menus": combined_database
    }
        
    with open('veri.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"\nTüm veriler başarıyla çekildi! Toplam taranan gün: {len(combined_database)} (Son Güncelleme: {guncel_zaman})")

if __name__ == "__main__":
    fetch_and_combine_menus()