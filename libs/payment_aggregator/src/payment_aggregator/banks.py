"""
Payout banks shared by every provider.

Classping bank code (as stored on payout accounts, the same for every
provider) -> (BI bank code, display name). DOKU (bank ID) and DANA
(beneficiaryBankCode) both take the BI code.
"""

BANKS = {
    "BCA": ("014", "BCA"),
    "BNI": ("009", "BNI"),
    "BRI": ("002", "BRI"),
    "MANDIRI": ("008", "Bank Mandiri"),
    "CIMB": ("022", "CIMB Niaga"),
    "SEABANK": ("535", "SeaBank"),
    "UOB": ("023", "UOB Indonesia"),
    "OCBC": ("028", "OCBC"),
    "DBS": ("046", "DBS Indonesia"),
    "MAYBANK": ("016", "Maybank Indonesia"),
    "MASPION": ("157", "Bank Maspion"),
    "STANCAR": ("050", "Standard Chartered"),
    "PERMATA": ("013", "Bank Permata"),
    "MAYAPADA": ("097", "Bank Mayapada"),
    "MEGA_SYR": ("506", "Bank Mega Syariah"),
    "ARTHA": ("037", "Bank Artha Graha"),
    "BCASYARIAH": ("536", "BCA Syariah"),
    "DANAMON": ("011", "Bank Danamon"),
    "BSI": ("451", "Bank Syariah Indonesia"),
    "MEGA": ("426", "Bank Mega"),
    "SINARMAS": ("153", "Bank Sinarmas"),
    "JAGO": ("542", "Bank Jago"),
    "BNC": ("490", "Bank Neo Commerce"),
    "SAHABAT_SAMPOERNA": ("523", "Bank Sahabat Sampoerna"),
    "BCA_DIGITAL": ("501", "BCA Digital (blu)"),
    "BISNIS_INTERNASIONAL": ("459", "Krom Bank (Bisnis Internasional)"),
    "INA_PERDANA": ("513", "Bank Ina Perdana"),
    "ALLO": ("567", "Allo Bank"),
    "HANA": ("484", "Bank KEB Hana"),
    "NOBU": ("503", "Nobu Bank"),
    "BTPN": ("213", "SMBC Indonesia (BTPN)"),
}
