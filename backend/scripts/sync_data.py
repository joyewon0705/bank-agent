import requests
import sqlite3
import os
from dotenv import load_dotenv

# TODO
# - 데이터 자동 적재 로직으로 개선
# - 새로 업데이트 된 데이터만 가져오도록
# - 정기예금이나 대출 API도 추가로 연결

# >> 실행 및 확인
# Cursor 터미널에서 아래 명령어를 쳐서 실제로 데이터를 가져오는지 확인
# python scripts/sync_data.py
# 성공했다면 폴더에 bank_data.db 파일 생성

# .env 파일에서 환경변수 로드
load_dotenv()

API_KEY = os.getenv("FINLIFE_API_KEY")
BASE_URL = "http://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"
DB_PATH = "bank_data.db"

def fetch_and_save_data():
    current_page = 1
    total_pages = 1
    all_base_list = []
    all_option_list = []

    print("🔄 금융 상품 데이터 수집 시작...")

    while current_page <= total_pages:
        params = {
            'auth': API_KEY,
            'topFinGrpNo': '020000',
            'pageNo': str(current_page)
        }
        
        try:
            response = requests.get(BASE_URL, params=params)
            data = response.json()
            result = data.get('result', {})
            
            # 첫 페이지에서 전체 페이지 수 파악
            if current_page == 1:
                total_pages = int(result.get('max_page_no', 1))
                print(f"📊 총 {total_pages} 페이지를 발견했습니다.")

            all_base_list.extend(result.get('baseList', []))
            all_option_list.extend(result.get('optionList', []))
            
            print(f"📥 {current_page}/{total_pages} 페이지 수집 중...")
            current_page += 1
            
        except Exception as e:
            print(f"❌ {current_page} 페이지 수집 중 오류: {e}")
            break

    # --- 여기서부터 DB 저장 로직 ---
    if not all_base_list:
        print("데이터가 없습니다.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 테이블 초기화 (일단은 덮어쓰기 방식으로 진행)
    cursor.execute('DROP TABLE IF EXISTS savings')
    cursor.execute('''
    CREATE TABLE savings (
        id TEXT PRIMARY KEY,
        bank_name TEXT,
        product_name TEXT,
        special_condition TEXT,
        intr_rate_type_nm TEXT,
        base_rate REAL,
        max_rate REAL,
        term INTEGER
    )
    ''')

    count = 0
    for base in all_base_list:
        # 해당 상품의 모든 기간 옵션을 뒤짐 (12, 24, 36개월 등)
        # 우선은 12개월을 기본으로 하되, 에이전트가 더 많은 정보를 알 수 있게 로직 확장 가능
        relevant_options = [
            opt for opt in all_option_list 
            if opt['fin_prdt_cd'] == base['fin_prdt_cd'] and str(opt['save_trm']) == "12"
        ]
        
        if not relevant_options:
            continue
            
        selected_opt = next((o for o in relevant_options if o['intr_rate_type'] == 'S'), relevant_options[0])
        
        base_rate = selected_opt.get('intr_rate') or 0.0
        max_rate = selected_opt.get('intr_rate2') or base_rate

        cursor.execute('INSERT OR REPLACE INTO savings VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (
            base['fin_prdt_cd'],
            base['kor_co_nm'],
            base['fin_prdt_nm'],
            base['spcl_cnd'],
            selected_opt['intr_rate_type_nm'],
            base_rate,
            max_rate,
            int(selected_opt['save_trm'])
        ))
        count += 1

    conn.commit()
    conn.close()
    print(f"✅ 동기화 완료: 총 {count}개의 상품이 저장되었습니다.")

if __name__ == "__main__":
    fetch_and_save_data()