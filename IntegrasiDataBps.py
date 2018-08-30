print("Tunggu...")

import geopandas as gp
import pandas as pd
import difflib
import numpy as np
import math
import re
import sys
from tabulate import tabulate
import os.path

def validate_id_prov(id_prov):
    if not id_prov :
        print("Masukkan ID provinsi")
        return False
    nama_prov = provdf.query("id_prov == "+ str(id_prov))["nama_prov"].max()
    if pd.isnull(nama_prov) :
        print("Tidak ada provinsi dengan ID tersebut")
        return False
    return nama_prov

def closest(a):
    try:
        if type(a) is str:
            return difflib.get_close_matches(a, list_kemendagrid_df)[0]        
    except IndexError:
        return "Not Found"

def similar(a, b):
    if a is not None and b is not None :
        return difflib.SequenceMatcher(None, a, b).ratio()

indonesia_filename = 'desa_webgis_bps.shp'
kemendagrid_csv = 'kemendagri.csv'

if not os.path.isfile(indonesia_filename) :
    print("Pastikan desa_webgis_bps.shp ada di folder yang sama dengan script ini")
    sys.exit()

if not os.path.isfile(kemendagrid_csv) :
    print("Pastikan kemendagri.csv ada di folder yang sama dengan script ini")
    sys.exit()
d = {'id_prov': [11,51,36,17,34,31,75,15,32,33,35,61,63,62,64,65,19,21,18,81,82,52,53,91,92,14,76,73,72,74,71,13,16,12], 
     'nama_prov': ['ACEH','BALI','BANTEN','BENGKULU','DAERAH ISTIMEWA YOGYAKARTA','DKI JAKARTA','GORONTALO','JAMBI','JAWA BARAT','JAWA TENGAH','JAWA TIMUR','KALIMANTAN BARAT','KALIMANTAN SELATAN','KALIMANTAN TENGAH','KALIMANTAN TIMUR','KALIMANTAN UTARA','KEPULAUAN BANGKA BELITUNG','KEPULAUAN RIAU','LAMPUNG','MALUKU','MALUKU UTARA','NUSA TENGGARA BARAT','NUSA TENGGARA TIMUR','PAPUA BARAT','PAPUA','RIAU','SULAWESI BARAT','SULAWESI SELATAN','SULAWESI TENGAH','SULAWESI TENGGARA','SULAWESI UTARA','SUMATERA BARAT','SUMATERA SELATAN','SUMATERA UTARA',
]}
provdf = pd.DataFrame(data=d)
print(tabulate(provdf, headers='keys', tablefmt='psql')) 

validated = False

while not validated :
    id_prov = int(input("ID Provinsi : "))
    validated = validate_id_prov(id_prov)    
    
if validated :    
    nama_prov = validated
    nama_prov_no_space = re.sub(r'\s','',nama_prov)

print("Memproses untuk provinsi " + nama_prov + " dengan ID provinsi "+ str(id_prov) )
print("------------------------------------------------------------------------")

#read indonesia file
print("Mempersiapkan data...")



indo_geo = gp.read_file(indonesia_filename)
if id_prov == 92 :
    id_prov_bps = 94
else :
    id_prov_bps = id_prov
    
prov_geo = indo_geo.loc[indo_geo['PROVNO'] == str(id_prov_bps)].copy()

print("Menggabung nama KABKOT, KECAMATAN, DAN DESA....")
prov_geo.loc[:,'concat_bps'] = prov_geo["KABKOT"].replace('\s','', regex=True) + prov_geo["KECAMATAN"].replace('\s','', regex=True) + prov_geo["DESA"].replace('\s','', regex=True)

    
kemendagrid_df = pd.read_csv('kemendagri.csv',sep=';') #kemendagri
kemendagrid_df_per_prov = kemendagrid_df.loc[kemendagrid_df['nama_provinsi'] == nama_prov]
list_kemendagrid_df = list(kemendagrid_df.loc[kemendagrid_df['nama_provinsi'] == nama_prov]["concatenate"])
kemendagrid_df.loc[:,"concatenate"] = kemendagrid_df["nama_kabupaten"].replace('\s','', regex=True) + kemendagrid_df["nama_kecamatan"].replace('\s','', regex=True) + kemendagrid_df["nama_desa"].replace('\s','', regex=True)

print("Mencari nama desa yang paling mirip.  Memakan waktu cukup lama.  Jangan dimatikan!!")
prov_geo['closest_village'] = prov_geo.apply(lambda row: closest(row['concat_bps']), axis=1)

#cari angka kesamaan antara nama desa
print("Memberi nilai kemiripan..")
if 'closest_village' in prov_geo.columns:
    prov_geo.rename(columns={'closest_village': 'concatenate'}, inplace=True)

    
prov_geo['similarity'] = prov_geo.apply(lambda row: similar(row['concat_bps'], row['concatenate']), axis=1)

#ambil concat yang tidak null dan dimerge ke data kemendagri
prov_geo_notnull = prov_geo[prov_geo['concatenate'].notnull()]
final_geodf_notnull = pd.merge(prov_geo_notnull,kemendagrid_df, on=['concatenate'], how="left")

#gabung dengan yang null
prov_geo_concat_isnull = prov_geo[prov_geo['concatenate'].isnull()]
final_geodf = pd.concat([final_geodf_notnull,prov_geo_concat_isnull],sort=False)
final_geodf_duplicated = final_geodf[final_geodf.duplicated(['concatenate'], keep=False)]
need_inspection = final_geodf_duplicated[['FID','IDDESA','KABKOT','KECAMATAN','DESA','concatenate']]
if 'cartodb_id' in final_geodf.columns:
    final_geodf.drop(columns=['cartodb_id'])
print("jumlah data awal : " + str(prov_geo.shape[0]))
print("jumlah data akhir : " + str(final_geodf.shape[0]))
if prov_geo.shape[0] == final_geodf.shape[0] :
    print("Jumlah data sama")
else :
    print("Jumlah data berbeda, data di bawah perlu dicek kembali : ")
    print(tabulate(need_inspection, headers='keys', tablefmt='psql'))

need_inspection.to_csv(nama_prov_no_space+"_perlu_dicek.csv")
final_geodf.to_file(nama_prov_no_space+"_final.shp");
