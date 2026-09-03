"""
Script de peuplement des directions et services du MTCA.
Basé sur l'organigramme officiel du Ministère du Tourisme, de la Culture et des Arts.

Usage:
    python manage.py shell -c "exec(open('courrier/seed_directions.py').read()); seed_directions()"
"""
from courrier.models import User

# ============================================================
# ORGANIGRAMME MTCA — Structures et membres à créer
# ============================================================

DIRECTIONS = [
    # (username, first_name, last_name, role, service_direction)
    
    # ===== CABINET DU MINISTRE =====
    ("dir_cabinet", "Directeur", "Cabinet", User.Role.DC, "Cabinet du Ministre"),
    ("ct_cabinet", "Conseiller", "Technique", User.Role.AGENT, "Cabinet du Ministre"),
    ("chm_cabinet", "Chargé", "Mission", User.Role.AGENT, "Cabinet du Ministre"),
    ("att_cabinet", "Attaché", "Cabinet", User.Role.AGENT, "Cabinet du Ministre"),
    ("att_presse", "Attaché", "Presse", User.Role.AGENT, "Cabinet du Ministre"),
    ("sec_ministre", "Secrétaire", "Particulier", User.Role.SECRETAIRE_MINISTRE, "Cabinet du Ministre"),

    # ===== SECRÉTARIAT GÉNÉRAL =====
    ("sg_mtca", "Secrétaire", "Général", User.Role.DIRECTEUR, "Secrétariat Général"),

    # ===== DIRECTIONS CENTRALES =====
    ("dir_daaf", "Directeur", "DAAF", User.Role.DIRECTEUR, "DAAF"),
    ("dir_dpdt", "Directeur", "DPDT", User.Role.DIRECTEUR, "DPDT"),
    ("dir_dpt", "Directeur", "DPT", User.Role.DIRECTEUR, "DPT"),
    ("dir_dricehb", "Directeur", "DRICEHB", User.Role.DIRECTEUR, "DRICEHB"),
    ("dir_dlpl", "Directeur", "DLPL", User.Role.DIRECTEUR, "DLPL"),
    ("dir_dpac", "Directeur", "DPAC", User.Role.DIRECTEUR, "DPAC"),
    ("dir_cncia", "Directeur", "CNCIA", User.Role.DIRECTEUR, "CNCIA"),
    ("dir_derpc", "Directeur", "DERPC", User.Role.DIRECTEUR, "DERPC"),
    ("dir_dpc", "Directeur", "DPC", User.Role.DIRECTEUR, "DPC"),
    ("dir_cenalac", "Directeur", "CENALAC", User.Role.DIRECTEUR, "CENALAC"),

    # ===== DIRECTIONS RÉGIONALES =====
    ("dir_drac_lome", "Directeur", "DRAC Grand-Lomé", User.Role.DIRECTEUR, "DRAC Grand-Lomé"),
    ("dir_drac_maritime", "Directeur", "DRAC Maritime", User.Role.DIRECTEUR, "DRAC Maritime"),
    ("dir_drac_plateaux", "Directeur", "DRAC Plateaux", User.Role.DIRECTEUR, "DRAC Plateaux"),
    ("dir_drac_centrale", "Directeur", "DRAC Centrale", User.Role.DIRECTEUR, "DRAC Centrale"),
    ("dir_drac_kara", "Directeur", "DRAC Kara", User.Role.DIRECTEUR, "DRAC Kara"),
    ("dir_drac_savanes", "Directeur", "DRAC Savanes", User.Role.DIRECTEUR, "DRAC Savanes"),

    # ===== SERVICES RATTACHÉS =====
    ("dir_prmp", "Directeur", "PRMP", User.Role.DIRECTEUR, "PRMP"),
    ("agent_cpmp", "Agent", "CPMP", User.Role.AGENT, "CPMP"),
    ("agent_ccmp", "Agent", "CCMP", User.Role.AGENT, "CCMP"),
    ("agent_comptable", "Agent", "Comptable", User.Role.AGENT, "Agent Comptable"),

    # ===== INSTITUTIONS ET ORGANISMES RATTACHÉS =====
    ("dir_fpdt", "Directeur", "FPDT", User.Role.DIRECTEUR, "FPDT"),
    ("dir_fnpc", "Directeur", "FNPC", User.Role.DIRECTEUR, "FNPC"),
    ("dir_cnacet", "Directeur", "CNACET", User.Role.DIRECTEUR, "CNACET"),
    ("dir_ires_rdec", "Directeur Général", "IRES-RDEC", User.Role.DIRECTEUR, "IRES-RDEC"),
    ("dir_butodra", "Directeur Général", "BUTODRA", User.Role.DIRECTEUR, "BUTODRA"),
    ("dir_cnpc", "Directeur", "CNPC", User.Role.DIRECTEUR, "CNPC"),
    ("dir_crfth", "Directeur", "CRFTH", User.Role.DIRECTEUR, "CRFTH"),
    ("dir_cct", "Président", "CCT", User.Role.DIRECTEUR, "CCT"),
]

def seed_directions():
    created = 0
    skipped = 0
    usernames = [item[0] for item in DIRECTIONS]
    existing_usernames = set(
        User.objects.filter(username__in=usernames).values_list('username', flat=True)
    )

    for username, first_name, last_name, role, service in DIRECTIONS:
        if username in existing_usernames:
            print(f"  [SKIP] {username} existe déjà.")
            skipped += 1
            continue

        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            role=role,
            service_direction=service,
            is_active=False,
        )
        user.set_unusable_password()
        user.save(update_fields=['password', 'is_active'])
        print(f"  [OK] Créé inactif : {user.get_full_name()} — {service} ({role})")
        created += 1

    print(f"\n{'='*50}")
    print(f"Terminé : {created} utilisateurs créés inactifs, {skipped} ignorés (existants).")
    print("Activez chaque compte et définissez un mot de passe fort depuis l'administration.")
    print(f"{'='*50}")


if __name__ == '__main__':
    seed_directions()
