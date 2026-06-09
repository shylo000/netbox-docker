#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
#  install_i18n.sh — Installe le support EN/FR dans le plugin netbox_device_search
#  Auteur : Jonathan AGNERAY — BTS CIEL 2026
#
#  USAGE :
#    1. Mets ce script dans ton dossier WSL (ex: ~/netbox-docker/)
#    2. chmod +x install_i18n.sh
#    3. ./install_i18n.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e  # Arrêter si une commande échoue

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
REPO="$(pwd)"
SRC="/mnt/c/Users/jonat/Documents/Claude/Projects/Netbox"
PLUGIN="$REPO/plugin/netbox_device_search"
TEMPLATES="$PLUGIN/templates/netbox_device_search"
LOCALE="$PLUGIN/locale"

# ── VÉRIFICATIONS ─────────────────────────────────────────────────────────────
echo "🔍 Vérification du répertoire courant..."
if [ ! -f "$REPO/Dockerfile-Plugins" ]; then
    echo "❌ Erreur : lance ce script depuis la racine de ton repo netbox-docker"
    echo "   cd ~/netbox-docker && ./install_i18n.sh"
    exit 1
fi
echo "✅ Repo détecté : $REPO"

# ── ÉTAPE 1 : views.py ────────────────────────────────────────────────────────
echo ""
echo "📝 [1/7] Mise à jour de views.py..."
cp "$SRC/views.py" "$PLUGIN/views.py"
echo "   ✓ views.py copié (avec switch_language)"

# ── ÉTAPE 2 : urls.py ─────────────────────────────────────────────────────────
echo ""
echo "🔗 [2/7] Mise à jour de urls.py..."
cp "$SRC/urls.py" "$PLUGIN/urls.py"
echo "   ✓ urls.py copié (avec route set-language/)"

# ── ÉTAPE 3 : Templates HTML ──────────────────────────────────────────────────
echo ""
echo "🎨 [3/7] Mise à jour des templates HTML..."
mkdir -p "$TEMPLATES"
cp "$SRC/search.html"         "$TEMPLATES/search.html"
cp "$SRC/results.html"        "$TEMPLATES/results.html"
cp "$SRC/create.html"         "$TEMPLATES/create.html"
cp "$SRC/detail.html"         "$TEMPLATES/detail.html"
cp "$SRC/dashboard.html"      "$TEMPLATES/dashboard.html"
cp "$SRC/_lang_switcher.html" "$TEMPLATES/_lang_switcher.html"
echo "   ✓ 6 templates copiés (dashboard.html inclus)"

# ── ÉTAPE 4 : Fichiers de traduction ──────────────────────────────────────────
echo ""
echo "🌍 [4/7] Création des fichiers de traduction..."
mkdir -p "$LOCALE/fr/LC_MESSAGES"
mkdir -p "$LOCALE/en/LC_MESSAGES"
cp "$SRC/django_fr.po" "$LOCALE/fr/LC_MESSAGES/django.po"
cp "$SRC/django_en.po" "$LOCALE/en/LC_MESSAGES/django.po"
echo "   ✓ locale/fr/LC_MESSAGES/django.po"
echo "   ✓ locale/en/LC_MESSAGES/django.po"

# ── ÉTAPE 5 : Dockerfile-Plugins ──────────────────────────────────────────────
echo ""
echo "🐳 [5/7] Mise à jour du Dockerfile-Plugins..."
cp "$SRC/Dockerfile-Plugins" "$REPO/Dockerfile-Plugins"
echo "   ✓ Dockerfile-Plugins mis à jour"

# ── ÉTAPE 6 : Rebuild Docker ──────────────────────────────────────────────────
echo ""
echo "🔨 [6/7] Rebuild de l'image Docker..."
docker compose down --remove-orphans
docker compose build netbox
echo "   ✓ Image construite"

# ── ÉTAPE 7 : Lancement ───────────────────────────────────────────────────────
echo ""
echo "🚀 [7/7] Démarrage des conteneurs..."
docker compose up -d
echo "   ✓ Conteneurs démarrés"

# ── RÉSUMÉ ────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Installation terminée !"
echo ""
echo "📁 Fichiers mis à jour :"
echo "   plugin/netbox_device_search/"
echo "   ├── views.py          (switch_language ajouté)"
echo "   ├── urls.py           (route set-language/ ajoutée)"
echo "   ├── locale/"
echo "   │   ├── fr/LC_MESSAGES/django.po"
echo "   │   └── en/LC_MESSAGES/django.po"
echo "   └── templates/netbox_device_search/"
echo "       ├── _lang_switcher.html  (URL corrigée)"
echo "       ├── dashboard.html       (switcher ajouté)"
echo "       ├── search.html"
echo "       ├── results.html"
echo "       ├── create.html"
echo "       └── detail.html"
echo ""
echo "🌐 Teste le switch : http://localhost:8000/plugins/device-search/"
echo "═══════════════════════════════════════════════════════"
