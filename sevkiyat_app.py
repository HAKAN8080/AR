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

        # CSV'leri oku
        def read_csv(uploaded_file):
            try:
                return pd.read_csv(uploaded_file, encoding="utf-8")
            except pd.errors.ParserError:
                return pd.read_csv(uploaded_file, encoding="utf-8", sep="\t")

        df = read_csv(sevkiyat_file)
        depo_stok_df = read_csv(depo_file)
        cover_df = read_csv(cover_file)
        kpi_df = read_csv(kpi_file)

        for d in [df, depo_stok_df, cover_df, kpi_df]:
            d.columns = d.columns.str.strip().str.replace('\ufeff','')

        if "yolda" not in df.columns:
            df["yolda"] = 0

        # KPI ve Cover ekle
        df = df.merge(kpi_df, on="klasmankod", how="left")
        df = df.merge(cover_df, on="magaza_id", how="left")
        df["cover"] = df["cover"].fillna(999)
        df_filtered = df[df["cover"] <= 20].copy()

        # İhtiyaç hesabı
        df_filtered["ihtiyac"] = (
            (df_filtered["haftalik_satis"] * df_filtered["hedef_hafta"])
            - (df_filtered["mevcut_stok"] + df_filtered["yolda"])
        ).clip(lower=0)

        df_sorted = df_filtered.sort_values(by=["urun_id", "haftalik_satis"], ascending=[True, False]).copy()

        # Sevkiyat planı
        sevk_listesi = []

        for (depo, urun), grup in df_sorted.groupby(["depo_id", "urun_id"]):
            stok_idx = (depo_stok_df["depo_id"] == depo) & (depo_stok_df["urun_id"] == urun)
            stok = int(depo_stok_df.loc[stok_idx, "depo_stok"].sum()) if stok_idx.any() else 0

            # Tur 1
            for _, row in grup.iterrows():
                min_adet = row["min_adet"] if pd.notna(row["min_adet"]) else 0
                MAKS_SEVK = row["maks_adet"] if pd.notna(row["maks_adet"]) else 200
                ihtiyac = row["ihtiyac"]
                sevk = int(min(ihtiyac, stok, MAKS_SEVK)) if stok > 0 and ihtiyac > 0 else 0
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
                    min_adet = row["min_adet"] if pd.notna(row["min_adet"]) else 0
                    MAKS_SEVK = row["maks_adet"] if pd.notna(row["maks_adet"]) else 200
                    mevcut = row["mevcut_stok"] + row["yolda"]
                    eksik_min = max(0, min_adet - mevcut)
                    sevk2 = int(min(eksik_min, stok, MAKS_SEVK)) if eksik_min > 0 else 0
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

            if stok_idx.any():
                depo_stok_df.loc[stok_idx, "depo_stok"] = stok
            else:
                depo_stok_df = pd.concat([depo_stok_df, pd.DataFrame([{
                    "depo_id": depo, "urun_id": urun, "depo_stok": stok
                }])], ignore_index=True)

        sevk_df = pd.DataFrame(sevk_listesi)

        # Çıktılar
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

        # -------------------------------
        # ✅ İlk 20 mağaza bazlı sevk miktarı grafiği
        # -------------------------------
        magaza_top20 = magaza_bazli.head(20)

        st.subheader("📊 En Çok Sevk Alan İlk 20 Mağaza (Sevk Miktarı)")

        chart = alt.Chart(magaza_top20).mark_bar().encode(
            x=alt.X('magaza_id:N', title='Mağaza ID'),
            y=alt.Y('sevk_miktar:Q', title='Toplam Sevk Miktarı'),
            color=alt.Color('sevk_miktar:Q', scale=alt.Scale(scheme='greens')),
            tooltip=['magaza_id', 'sevk_miktar']
        )

        st.altair_chart(chart, use_container_width=True)

        # -------------------------------
        # ✅ Özet KPI’lar
        # -------------------------------
        st.subheader("📊 Genel KPI’lar")
        st.write(f"Toplam Sevk: {toplam_sevk_adet}")
        st.write(f"Toplam Min Tamamlama: {toplam_min_tamamlama}")
        st.write(f"Toplam Mağaza: {toplam_magaza}")
        st.write(f"Toplam Satır: {toplam_satir}")
        st.write(f"⏱️ İşlem süresi: {sure_sn} saniye")

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
