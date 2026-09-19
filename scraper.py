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
    print("Siteye bağlanılıyor ve tarih bilgileri alınıyor...")
    
    try:
        init_res = session.get(URL, verify=False)
        init_res.encoding = 'utf-8'
        soup = BeautifulSoup(init_res.text, 'html.parser')
        
        yil_input = soup.find('input', id='Yil')
        ay_input = soup.find('input', id='Ay')
        
        guncel_yil = yil_input['value'] if yil_input else str(datetime.now().year)
        guncel_ay = ay_input['value'] if ay_input else str(datetime.now().month)
    except Exception as e:
        print("Tarih bilgisi alınamadı, yerel tarih kullanılıyor...", e)
        guncel_yil = str(datetime.now().year)
        guncel_ay = str(datetime.now().month)

    print(f"Hedef Tarih: {guncel_ay}/{guncel_yil}")

    def get_menu_for_meal(meal_code):
        data = {
            "Yil": guncel_yil,
            "Ay": guncel_ay,
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
                        
                        # İçindekiler kısmını HTML etiketlerinden ayıklayarak çekme
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

    print("Öğle menüleri çekiliyor...")
    ogle_verisi = get_menu_for_meal("1")
    
    print("Akşam menüleri çekiliyor...")
    aksam_verisi = get_menu_for_meal("2")
    
    combined_database = {}
    all_dates = set(ogle_verisi.keys()).union(set(aksam_verisi.keys()))
    
    for date in sorted(all_dates):
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
        
    print(f"Tüm veriler başarıyla çekildi! (Son Güncelleme: {guncel_zaman})")

if __name__ == "__main__":
    fetch_and_combine_menus()