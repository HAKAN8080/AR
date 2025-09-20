import streamlit as st
import pandas as pd
import time
import altair as alt

# -------------------------------
# 0️⃣ Sayfa yapılandırması ve tema
# -------------------------------
st.set_page_config(
    page_title="EVE Sevkiyat Planlama",
    page_icon="📦",
    layout="wide"
)

# CSS ile küçük görsel iyileştirmeler
st.markdown(
    """
    <style>
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        padding: 10px 20px;
        border-radius: 8px;
        border: none;
        font-size: 16px;
        cursor: pointer;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .stFileUploader>div {
        border: 2px dashed #4CAF50;
        border-radius: 8px;
        padding: 10px;
        background-color: #f9f9f9;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📦 Sevkiyat Planlama Uygulaması")
st.markdown("**Adım 1:** CSV dosyalarını yükleyin ve ardından hesaplayın.", unsafe_allow_html=True)

# -------------------------------
# 1️⃣ CSV yükleme alanları (iki sütunlu düzen)
# -------------------------------
col1, col2 = st.columns(2)

with col1:
    sevkiyat_file = st.file_uploader("Sevkiyat CSV yükle", type=["csv"])
    depo_file = st.file_uploader("Depo Stok CSV yükle", type=["csv"])

with col2:
    cover_file = st.file_uploader("Cover CSV yükle", type=["csv"])
    kpi_file = st.file_uploader("KPI CSV yükle", type=["csv"])

st.markdown("---")  # yatay ayırıcı

# -------------------------------
# 2️⃣ Hesapla butonu
# -------------------------------
if st.button("🚀 Hesapla"):
    if not (sevkiyat_file and depo_file and cover_file and kpi_file):
        st.error("⚠️ Lütfen tüm dosyaları yükleyin!")
    else:
        start_time = time.time()
        
        # İlerleme çubuğu
        progress_bar = st.progress(0)
        status_text = st.empty()

        # CSV'leri oku
        def read_csv(uploaded_file):
            try:
                return pd.read_csv(uploaded_file, encoding="utf-8")
            except UnicodeDecodeError:
                return pd.read_csv(uploaded_file, encoding="iso-8859-9")
            except pd.errors.ParserError:
                return pd.read_csv(uploaded_file, encoding="utf-8", sep="\t")
            except Exception as e:
                st.error(f"Dosya okuma hatası: {str(e)}")
                return pd.DataFrame()

        status_text.text("Dosyalar okunuyor...")
        df = read_csv(sevkiyat_file)
        depo_stok_df = read_csv(depo_file)
        cover_df = read_csv(cover_file)
        kpi_df = read_csv(kpi_file)
        progress_bar.progress(25)

        # Boş DataFrame kontrolü
        if any([df.empty, depo_stok_df.empty, cover_df.empty, kpi_df.empty]):
            st.error("Bir veya daha fazla dosya okunamadı veya boş!")
            st.stop()

        # Sütun isimlerini temizle
        for d in [df, depo_stok_df, cover_df, kpi_df]:
            d.columns = d.columns.str.strip().str.replace('^\ufeff', '', regex=True)

        # Sayısal sütunları uygun tipe dönüştür
        numeric_columns = ['yolda', 'haftalik_satis', 'hedef_hafta', 'mevcut_stok', 'cover', 
                          'min_adet', 'maks_adet', 'depo_stok']
        
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            if col in depo_stok_df.columns:
                depo_stok_df[col] = pd.to_numeric(depo_stok_df[col], errors='coerce').fillna(0)

        if "yolda" not in df.columns:
            df["yolda"] = 0

        status_text.text("Veriler birleştiriliyor...")
        # KPI ve Cover ekle
        df = df.merge(kpi_df, on="klasmankod", how="left")
        df = df.merge(cover_df, on="magaza_id", how="left")
        df["cover"] = df["cover"].fillna(999)
        df_filtered = df[df["cover"] <= 20].copy()
        progress_bar.progress(50)

        # İhtiyaç hesabı
        df_filtered["ihtiyac"] = (
            (df_filtered["haftalik_satis"] * df_filtered["hedef_hafta"])
            - (df_filtered["mevcut_stok"] + df_filtered["yolda"])
        ).clip(lower=0)

        df_sorted = df_filtered.sort_values(by=["urun_id", "haftalik_satis"], ascending=[True, False]).copy()

        status_text.text("Sevkiyat planı oluşturuluyor...")
        # Sevkiyat planı
        sevk_listesi = []
        total_groups = df_sorted.groupby(["depo_id", "urun_id"]).ngroups
        processed_groups = 0

        for (depo, urun), grup in df_sorted.groupby(["depo_id", "urun_id"]):
            stok_idx = (depo_stok_df["depo_id"] == depo) & (depo_stok_df["urun_id"] == urun)
            stok = int(depo_stok_df.loc[stok_idx, "depo_stok"].sum()) if stok_idx.any() else 0

            # Tur 1
            for _, row in grup.iterrows():
                min_adet = row["min_adet"] if pd.notnull(row["min_adet"]) else 0
                MAKS_SEVK = row["maks_adet"] if pd.notnull(row["maks_adet"]) else 200
                ihtiyac = row["ihtiyac"]
                sevk = int(min(ihtiyac, stok, MAKS_SEVK)) if stok > 0 and ihtiyac > 0 else 0
                if sevk > 0:
                    stok -= sevk
                    sevk_listesi.append({
                        "depo_id": depo,
                        "magaza_id": row["magaza_id"],
                        "urun_id": urun,
                        "klasmankod": row["klasmankod"],
                        "tur": 1,
                        "ihtiyac": ihtiyac,
                        "yolda": row["yolda"],
                        "sevk_miktar": sevk,
                        "haftalik_satis": row["haftalik_satis"],
                        "mevcut_stok": row["mevcut_stok"],
                        "cover": row["cover"]
                    })

            # Tur 2
            if stok > 0:
                for _, row in grup.iterrows():
                    if row["cover"] >= 12:
                        continue
                    min_adet = row["min_adet"] if pd.notnull(row["min_adet"]) else 0
                    MAKS_SEVK = row["maks_adet"] if pd.notnull(row["maks_adet"]) else 200
                    mevcut = row["mevcut_stok"] + row["yolda"]
                    eksik_min = max(0, min_adet - mevcut)
                    sevk2 = int(min(eksik_min, stok, MAKS_SEVK)) if eksik_min > 0 else 0
                    if sevk2 > 0:
                        stok -= sevk2
                        sevk_listesi.append({
                            "depo_id": depo,
                            "magaza_id": row["magaza_id"],
                            "urun_id": urun,
                            "klasmankod": row["klasmankod"],
                            "tur": 2,
                            "ihtiyac": row["ihtiyac"],
                            "yolda": row["yolda"],
                            "sevk_miktar": sevk2,
                            "haftalik_satis": row["haftalik_satis"],
                            "mevcut_stok": row["mevcut_stok"],
                            "cover": row["cover"]
                        })

            # Depo stok güncelleme - daha güvenli versiyon
            if stok_idx.any():
                if stok_idx.sum() == 1:  # Sadece bir satır eşleşiyorsa
                    depo_stok_df.loc[stok_idx, "depo_stok"] = stok
                else:  # Birden fazla satır eşleşiyorsa, ilkini güncelle
                    first_match_idx = stok_idx.idxmax()
                    depo_stok_df.loc[first_match_idx, "depo_stok"] = stok
            else:
                depo_stok_df = pd.concat([depo_stok_df, pd.DataFrame([{
                    "depo_id": depo, "urun_id": urun, "depo_stok": stok
                }])], ignore_index=True)
            
            processed_groups += 1
            progress_bar.progress(50 + int(40 * processed_groups / total_groups))

        sevk_df = pd.DataFrame(sevk_listesi)
        progress_bar.progress(95)

        # Çıktılar
        if not sevk_df.empty:
            total_sevk = sevk_df.groupby(
                ["depo_id", "magaza_id", "urun_id", "klasmankod"], as_index=False
            ).agg({
                "sevk_miktar": "sum",
                "yolda": "first",
                "haftalik_satis": "first",
                "ihtiyac": "first",
                "mevcut_stok": "first",
                "cover": "first"
            })

            toplam_sevk_adet = total_sevk["sevk_miktar"].sum()
            toplam_magaza = total_sevk["magaza_id"].nunique()
            toplam_satir = sevk_df.shape[0]
            toplam_min_tamamlama = sevk_df[sevk_df["tur"] == 2]["sevk_miktar"].sum()

            magaza_bazli = total_sevk.groupby("magaza_id")["sevk_miktar"].sum().reset_index().sort_values(by="sevk_miktar", ascending=False)
            urun_bazli = total_sevk.groupby("urun_id")["sevk_miktar"].sum().reset_index().sort_values(by="sevk_miktar", ascending=False)

            end_time = time.time()
            sure_sn = round(end_time - start_time, 2)

            status_text.text("Sonuçlar gösteriliyor...")
            # -------------------------------
            # ✅ İlk 20 mağaza bazlı sevk miktarı grafiği
            # -------------------------------
            magaza_top20 = magaza_bazli.head(20)

            st.subheader("📊 En Çok Sevk Alan İlk 20 Mağaza (Sevk Miktarı)")

            chart = alt.Chart(magaza_top20).mark_bar().encode(
                x=alt.X('magaza_id:N', title='Mağaza ID', sort='-y'),
                y=alt.Y('sevk_miktar:Q', title='Toplam Sevk Miktarı'),
                color=alt.Color('sevk_miktar:Q', scale=alt.Scale(scheme='greens')),
                tooltip=['magaza_id', 'sevk_miktar']
            ).properties(height=400)

            st.altair_chart(chart, use_container_width=True)

            # -------------------------------
            # ✅ Özet KPI’lar
            # -------------------------------
            st.subheader("📊 Genel KPI'lar")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Toplam Sevk", f"{toplam_sevk_adet:,}")
            with col2:
                st.metric("Min Tamamlama", f"{toplam_min_tamamlama:,}")
            with col3:
                st.metric("Toplam Mağaza", f"{toplam_magaza:,}")
            with col4:
                st.metric("İşlem Süresi", f"{sure_sn} saniye")

            # -------------------------------
            # ✅ CSV indirme butonu
            # -------------------------------
            csv_out = total_sevk.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Sonuç CSV indir",
                data=csv_out,
                file_name="sevkiyat_sonuc.csv",
                mime="text/csv"
            )
            
            # Önizleme tablosu
            st.subheader("📋 Sevkiyat Önizleme (İlk 10 satır)")
            st.dataframe(total_sevk.head(10))
        else:
            st.warning("Hiç sevkiyat planlanamadı. Lütfen verilerinizi kontrol edin.")
        
        progress_bar.progress(100)
        status_text.text("Hesaplama tamamlandı!")
        time.sleep(0.5)
        progress_bar.empty()
        status_text.empty()