#!/bin/bash

echo "🔌 Installation Automatique du Plugin Device Search"
echo "===================================================="
echo ""

# Vérifier qu'on est dans le bon répertoire
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Erreur: Vous devez exécuter ce script depuis ~/netbox-docker"
    echo "Usage: cd ~/netbox-docker && bash ~/install_plugin.sh"
    exit 1
fi

echo "📂 Répertoire actuel: $(pwd)"
echo ""

# Étape 1 : Créer les fichiers nécessaires
echo "1️⃣ Création des fichiers de configuration..."

# plugin_requirements.txt
cat > plugin_requirements.txt << 'EOF'
# Plugin Requirements pour Netbox
# Ajoutez ici les plugins PyPI si nécessaire
# Exemple: netbox-secrets

# Notre plugin device_search est local, pas besoin de l'ajouter ici
EOF
echo "   ✅ plugin_requirements.txt créé"

# Dockerfile-Plugins
cat > Dockerfile-Plugins << 'EOF'
FROM netboxcommunity/netbox:latest

# Copier les requirements des plugins PyPI (si nécessaire)
COPY ./plugin_requirements.txt /opt/netbox/
RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt

# Copier le plugin local device_search
COPY ./plugin/device_search /opt/netbox/netbox/plugins/device_search

# Copier les fichiers de configuration
COPY configuration/configuration.py /etc/netbox/config/configuration.py
COPY configuration/plugins.py /etc/netbox/config/plugins.py

# Collecter les fichiers statiques du plugin
RUN DEBUG="true" SECRET_KEY="dummydummydummydummydummydummydummydummydummydummy" \
    /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input
EOF
echo "   ✅ Dockerfile-Plugins créé"

# docker-compose.override.yml
cat > docker-compose.override.yml << 'EOF'
services:
  netbox:
    image: netbox:latest-plugins
    pull_policy: never
    ports:
      - 8000:8080
    build:
      context: .
      dockerfile: Dockerfile-Plugins
  
  netbox-worker:
    image: netbox:latest-plugins
    pull_policy: never
    ports: []  # Pas de ports pour le worker
  
  netbox-housekeeping:
    image: netbox:latest-plugins
    pull_policy: never
EOF
echo "   ✅ docker-compose.override.yml créé"

echo ""

# Étape 2 : Copier le plugin
echo "2️⃣ Copie du plugin device_search..."

if [ -d "$HOME/netbox-project/plugins/device_search" ]; then
    mkdir -p plugin
    cp -r "$HOME/netbox-project/plugins/device_search" plugin/
    echo "   ✅ Plugin copié depuis ~/netbox-project"
else
    echo "   ❌ Erreur: Plugin non trouvé dans ~/netbox-project/plugins/device_search"
    echo "   Assurez-vous que le projet netbox-project existe"
    exit 1
fi

echo ""

# Étape 3 : Configuration du plugin
echo "3️⃣ Configuration du plugin..."

mkdir -p configuration

cat > configuration/plugins.py << 'EOF'
# Configuration des plugins Netbox

PLUGINS = ["device_search"]

PLUGINS_CONFIG = {
    "device_search": {
        "enabled": True,
    }
}
EOF
echo "   ✅ configuration/plugins.py créé"

echo ""

# Vérification de la structure
echo "📋 Vérification de la structure..."
echo ""
echo "Fichiers créés:"
ls -1 plugin_requirements.txt Dockerfile-Plugins docker-compose.override.yml 2>/dev/null | sed 's/^/   ✅ /'
echo ""
echo "Plugin copié:"
if [ -d "plugin/device_search" ]; then
    echo "   ✅ plugin/device_search/"
    ls -1 plugin/device_search/*.py 2>/dev/null | sed 's/^/      - /'
else
    echo "   ❌ plugin/device_search/ manquant"
fi
echo ""
echo "Configuration:"
if [ -f "configuration/plugins.py" ]; then
    echo "   ✅ configuration/plugins.py"
else
    echo "   ❌ configuration/plugins.py manquant"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -p "Voulez-vous construire l'image Docker maintenant ? (o/n) " -n 1 -r
echo
echo ""

if [[ ! $REPLY =~ ^[Oo]$ ]]; then
    echo "Installation des fichiers terminée."
    echo ""
    echo "Pour construire l'image plus tard, exécutez :"
    echo "   cd ~/netbox-docker"
    echo "   docker compose down"
    echo "   docker compose build --no-cache"
    echo "   docker compose up -d"
    exit 0
fi

# Étape 4 : Construction
echo "4️⃣ Construction de l'image Docker personnalisée..."
echo ""
echo "⚠️  Cela peut prendre 2-5 minutes..."
echo ""

# Arrêter les conteneurs
echo "   🛑 Arrêt des conteneurs actuels..."
docker compose down

echo ""
echo "   🔨 Construction de l'image (cela peut être long)..."
docker compose build --no-cache

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Erreur lors de la construction de l'image"
    echo ""
    echo "Pour voir les détails de l'erreur, exécutez :"
    echo "   docker compose --progress plain build --no-cache"
    exit 1
fi

echo ""
echo "   ✅ Image construite avec succès"

echo ""
echo "5️⃣ Démarrage des conteneurs..."
docker compose up -d

echo ""
echo "   ⏳ Attente du démarrage (30 secondes)..."
sleep 30

echo ""
echo "6️⃣ Vérification..."
echo ""

# Vérifier l'état
echo "📊 État des conteneurs:"
docker compose ps

echo ""
echo "🔍 Vérification du plugin dans l'image..."
docker compose exec netbox ls -la /opt/netbox/netbox/plugins/device_search/ 2>/dev/null

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Plugin trouvé dans l'image !"
else
    echo ""
    echo "⚠️  Impossible de vérifier le plugin (le conteneur démarre peut-être encore)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎉 Installation terminée !"
echo ""
echo "📝 Prochaines étapes:"
echo ""
echo "1. Ouvrir votre navigateur sur: http://localhost:8000"
echo "2. Se connecter avec vos identifiants"
echo "3. Vérifier que 'Plugins' apparaît dans le menu"
echo "4. Cliquer sur 'Device Search Plugin'"
echo ""
echo "🔍 Pour vérifier que le plugin est chargé:"
echo "   docker compose exec netbox python /opt/netbox/netbox/manage.py shell"
echo "   >>> from django.conf import settings"
echo "   >>> settings.PLUGINS"
echo "   >>> exit()"
echo ""
echo "📋 Logs en cas de problème:"
echo "   docker compose logs --tail=100 netbox"
echo ""
