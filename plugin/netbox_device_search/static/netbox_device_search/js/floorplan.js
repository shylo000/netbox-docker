/**
 * Plan d'usine interactif — marqueurs de baies, zoom/pan, mode placement.
 *
 * ─── Le principe qui tient tout ────────────────────────────────────────────
 * Les positions sont en POURCENTAGES de l'image, jamais en pixels. Un marqueur
 * posé à (42.5, 61.3) reste au bon endroit qu'on zoome, qu'on redimensionne la
 * fenêtre, ou qu'on remplace le plan par un export deux fois plus grand.
 * Le navigateur fait le calcul tout seul via `left: 42.5%`.
 *
 * Écrit en JS natif, sans dépendance externe : le conteneur NetBox tourne
 * derrière le pare-feu de Clarebout, un CDN ne serait pas joignable.
 */
(function () {
    'use strict';

    const cfg = document.getElementById('fp-config');
    if (!cfg) { return; }

    const viewport = document.getElementById('plan-viewport');
    const stage = document.getElementById('plan-stage');
    const image = document.getElementById('plan-image');
    const markersLayer = document.getElementById('markers');

    const canEdit = cfg.dataset.canEdit === '1';
    const planSlug = cfg.dataset.planSlug;

    let racks = JSON.parse(document.getElementById('racks-data').textContent || '[]');

    // État de la vue : facteur d'échelle + décalage, appliqués en une seule
    // transform CSS (le GPU s'en charge, c'est fluide même sur un gros PNG).
    let scale = 1, offsetX = 0, offsetY = 0;
    let armedRackId = null;   // baie sélectionnée en attente d'être posée
    let editMode = false;     // mode placement actif ou non

    // Texte d'aide initial, capturé avant toute modification pour pouvoir y
    // revenir. On le lit dans le DOM plutôt que de le coder en dur : il est
    // traduit par Django, le JS n'a pas à connaître la langue courante.
    const defaultInstruction =
        (document.getElementById('edit-instruction') || {}).textContent || '';

    // ═══════════════════════════════════════════════════════════════════════
    //  Utilitaires
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Récupère le jeton CSRF. Sans lui, tout POST est rejeté en 403 — c'est
     * voulu : c'est exactement ce qui empêche un site tiers de forger une
     * requête au nom de l'utilisateur.
     *
     * Deux sources, dans cet ordre :
     *   1. Le champ rendu par {% csrf_token %} dans le template. Source
     *      officiellement recommandée par Django, et la seule qui fonctionne
     *      si CSRF_COOKIE_HTTPONLY vaut True — auquel cas document.cookie ne
     *      voit tout simplement pas le cookie.
     *   2. Le cookie, en repli, si le template ne rend pas le champ.
     */
    function getCsrfToken() {
        const field = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (field && field.value) { return field.value; }

        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function rackUrl(rackId) {
        // L'URL modèle est générée côté Django avec l'id 0 ; on substitue.
        return cfg.dataset.urlRackBase.replace(/0\/$/, rackId + '/');
    }

    function statusColor(status) {
        if (status === 'active') { return '#14B8A6'; }   // teal
        if (status === 'planned') { return '#0EA5E9'; }  // bleu
        return '#F59E0B';                                 // orange
    }

    function setInstruction(text) {
        const el = document.getElementById('edit-instruction');
        if (el) { el.textContent = text; }
    }

    /** Aucune baie en attente : on relâche la sélection et les indices visuels. */
    function disarm() {
        armedRackId = null;
        viewport.classList.remove('is-placing');
        document.querySelectorAll('.rack-pick.is-armed')
                .forEach(el => el.classList.remove('is-armed'));
        setInstruction(defaultInstruction);
    }

    /**
     * Arme une baie : le prochain clic sur le plan la posera.
     *
     * Même fonction pour une baie jamais placée et pour une baie qu'on déplace.
     * C'est volontaire : côté serveur, poser et déplacer sont la même écriture,
     * donc autant ne pas inventer deux chemins de code pour une seule opération.
     */
    function arm(rackId, rackName) {
        disarm();
        armedRackId = rackId;
        viewport.classList.add('is-placing');
        setInstruction(cfg.dataset.labelClickPlan + ' « ' + rackName + ' »');

        const listItem = document.querySelector(
            '.rack-pick[data-rack-id="' + rackId + '"]');
        if (listItem) { listItem.classList.add('is-armed'); }
    }

    function toast(message, isError) {
        const el = document.createElement('div');
        el.className = 'alert ' + (isError ? 'alert-danger' : 'alert-success') +
                       ' shadow position-fixed';
        el.style.cssText = 'bottom:1rem; right:1rem; z-index:1080; padding:.5rem .9rem;';
        el.textContent = message;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 2500);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  Rendu des marqueurs
    // ═══════════════════════════════════════════════════════════════════════

    function renderMarkers() {
        markersLayer.innerHTML = '';

        racks.forEach(rack => {
            const marker = document.createElement('div');
            marker.className = 'fp-marker';
            marker.style.left = rack.x + '%';
            marker.style.top = rack.y + '%';
            marker.dataset.rackId = rack.id;

            const body = document.createElement('div');
            body.className = 'fp-marker-body';
            body.style.borderColor = statusColor(rack.status_value);

            const dot = document.createElement('span');
            dot.className = 'fp-dot';
            dot.style.background = statusColor(rack.status_value);
            dot.style.margin = '0';

            const name = document.createElement('span');
            name.textContent = rack.name;

            const count = document.createElement('span');
            count.className = 'fp-marker-count';
            count.textContent = rack.device_count;

            body.append(dot, name, count);
            marker.appendChild(body);

            marker.title = rack.name + ' — ' + rack.site +
                (rack.location ? ' / ' + rack.location : '') +
                ' — ' + rack.device_count + ' ' + cfg.dataset.labelDevices;

            /*
             * Le clic gauche a deux sens selon le mode, et c'est ce qui rend
             * le déplacement découvrable sans rien apprendre :
             *   — hors mode placement → on ouvre la fiche de la baie ;
             *   — en mode placement   → on « reprend » la baie, le clic
             *     suivant sur le plan la repose ailleurs.
             * Un double-clic ou un Ctrl+clic aurait marché aussi, mais
             * personne ne le devine. Ici le mode est déjà visible à l'écran
             * (bandeau jaune, curseur en croix) : le geste suit le contexte.
             */
            marker.addEventListener('click', ev => {
                ev.stopPropagation();   // ne pas déclencher un placement

                if (canEdit && editMode) {
                    arm(rack.id, rack.name);
                    return;
                }
                window.location.href = rackUrl(rack.id);
            });

            // Clic droit en mode édition → retirer du plan.
            if (canEdit) {
                marker.addEventListener('contextmenu', ev => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    if (confirm(cfg.dataset.labelRemove + ' : ' + rack.name + ' ?')) {
                        clearPosition(rack.id);
                    }
                });
            }

            markersLayer.appendChild(marker);
        });

        document.getElementById('placed-count').textContent = racks.length;
        applyCounterScale();
    }

    /**
     * Les marqueurs sont dans le conteneur zoomé : sans correction ils
     * grossiraient avec le plan et deviendraient énormes. On leur applique
     * l'échelle inverse pour qu'ils gardent une taille lisible constante —
     * c'est le comportement attendu d'une carte (les pastilles de Google Maps
     * ne grossissent pas quand on zoome).
     */
    function applyCounterScale() {
        const inverse = 1 / scale;
        markersLayer.querySelectorAll('.fp-marker').forEach(marker => {
            marker.style.transform = 'translate(-50%, -50%) scale(' + inverse + ')';
        });
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  Zoom / déplacement
    // ═══════════════════════════════════════════════════════════════════════

    function applyTransform() {
        stage.style.transform =
            'translate(' + offsetX + 'px, ' + offsetY + 'px) scale(' + scale + ')';
        applyCounterScale();
    }

    /** Ajuste le plan pour qu'il tienne entièrement dans le cadre, centré. */
    function fitToViewport() {
        if (!image.naturalWidth) { return; }
        const rect = viewport.getBoundingClientRect();
        scale = Math.min(rect.width / image.naturalWidth,
                         rect.height / image.naturalHeight);
        offsetX = (rect.width - image.naturalWidth * scale) / 2;
        offsetY = (rect.height - image.naturalHeight * scale) / 2;
        applyTransform();
    }

    /**
     * Zoom centré sur un point donné (le curseur), et non sur le coin haut-gauche.
     * On corrige l'offset pour que le pixel sous la souris reste sous la souris :
     * sans ça, zoomer fait fuir la zone qu'on regarde.
     */
    function zoomAt(clientX, clientY, factor) {
        const rect = viewport.getBoundingClientRect();
        const px = clientX - rect.left;
        const py = clientY - rect.top;

        const newScale = Math.min(8, Math.max(0.1, scale * factor));
        const ratio = newScale / scale;

        offsetX = px - (px - offsetX) * ratio;
        offsetY = py - (py - offsetY) * ratio;
        scale = newScale;
        applyTransform();
    }

    viewport.addEventListener('wheel', ev => {
        ev.preventDefault();
        zoomAt(ev.clientX, ev.clientY, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });

    document.getElementById('zoom-in').addEventListener('click', () => {
        const r = viewport.getBoundingClientRect();
        zoomAt(r.left + r.width / 2, r.top + r.height / 2, 1.3);
    });
    document.getElementById('zoom-out').addEventListener('click', () => {
        const r = viewport.getBoundingClientRect();
        zoomAt(r.left + r.width / 2, r.top + r.height / 2, 1 / 1.3);
    });
    document.getElementById('zoom-reset').addEventListener('click', fitToViewport);

    // ── Pan à la souris ──
    let isPanning = false, panStartX = 0, panStartY = 0, movedDistance = 0;

    viewport.addEventListener('mousedown', ev => {
        if (ev.button !== 0) { return; }
        isPanning = true;
        movedDistance = 0;
        panStartX = ev.clientX - offsetX;
        panStartY = ev.clientY - offsetY;
        viewport.classList.add('is-panning');
    });

    window.addEventListener('mousemove', ev => {
        if (!isPanning) { return; }
        const nextX = ev.clientX - panStartX;
        const nextY = ev.clientY - panStartY;
        movedDistance += Math.abs(nextX - offsetX) + Math.abs(nextY - offsetY);
        offsetX = nextX;
        offsetY = nextY;
        applyTransform();
    });

    window.addEventListener('mouseup', () => {
        isPanning = false;
        viewport.classList.remove('is-panning');
    });

    // ═══════════════════════════════════════════════════════════════════════
    //  Mode placement
    // ═══════════════════════════════════════════════════════════════════════

    if (canEdit) {
        const btnToggle = document.getElementById('btn-toggle-edit');
        const panel = document.getElementById('unplaced-panel');
        const planCol = document.getElementById('plan-col');
        const banner = document.getElementById('edit-banner');

        btnToggle.addEventListener('click', () => {
            editMode = !editMode;
            panel.classList.toggle('d-none', !editMode);
            banner.classList.toggle('d-none', !editMode);
            banner.classList.toggle('d-flex', editMode);
            // Le plan rétrécit pour laisser la place au panneau latéral.
            planCol.className = editMode ? 'col-lg-9' : 'col-12';
            btnToggle.classList.toggle('btn-warning', editMode);
            btnToggle.classList.toggle('btn-outline-warning', !editMode);
            viewport.classList.toggle('is-placing', editMode && armedRackId !== null);
            // Sert à passer les marqueurs en curseur "move" : en mode placement
            // ils ne sont plus des liens, ce sont des objets déplaçables.
            viewport.classList.toggle('is-editing', editMode);
            if (!editMode) { disarm(); }
            // La largeur du cadre a changé : on recadre.
            setTimeout(fitToViewport, 250);
        });

        // Sélection d'une baie dans la liste de gauche.
        document.getElementById('unplaced-list').addEventListener('click', ev => {
            const button = ev.target.closest('.rack-pick');
            if (!button) { return; }
            arm(parseInt(button.dataset.rackId, 10), button.dataset.rackName);
        });

        // Filtre de la liste (utile quand le parc grandit).
        document.getElementById('rack-filter').addEventListener('input', ev => {
            const needle = ev.target.value.toLowerCase();
            document.querySelectorAll('.rack-pick').forEach(el => {
                el.style.display =
                    el.textContent.toLowerCase().includes(needle) ? '' : 'none';
            });
        });

        /**
         * Clic sur le plan = pose de la baie armée.
         *
         * On calcule le % à partir du rectangle réel de l'IMAGE
         * (getBoundingClientRect tient déjà compte du zoom et du pan appliqués
         * par la transform) — donc aucun calcul manuel à refaire quand la vue
         * change. C'est le raccourci qui évite toute une classe de bugs.
         */
        viewport.addEventListener('click', ev => {
            if (!editMode || armedRackId === null) { return; }
            if (movedDistance > 5) { return; }   // c'était un pan, pas un clic

            const rect = image.getBoundingClientRect();
            const x = ((ev.clientX - rect.left) / rect.width) * 100;
            const y = ((ev.clientY - rect.top) / rect.height) * 100;
            if (x < 0 || x > 100 || y < 0 || y > 100) { return; }

            savePosition(armedRackId, x, y);
        });
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  Appels serveur
    // ═══════════════════════════════════════════════════════════════════════

    function post(url, payload) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(payload),
        }).then(response => {
            if (!response.ok) { throw new Error('HTTP ' + response.status); }
            return response.json();
        });
    }

    function savePosition(rackId, x, y) {
        post(cfg.dataset.urlSave, { rack_id: rackId, plan: planSlug, x: x, y: y })
            .then(data => {
                const saved = data.rack;

                // Mise à jour optimiste de l'affichage : on ne recharge pas la
                // page, pour ne pas perdre le zoom et la position courants.
                //
                // Le tableau `racks` est indexé par identifiant de baie, pas
                // par ordre d'insertion : une baie déjà présente est DÉPLACÉE,
                // jamais ajoutée une seconde fois. Un push inconditionnel
                // créait un doublon à chaque repositionnement — le serveur,
                // lui, n'a toujours stocké qu'une position, si bien que les
                // doublons disparaissaient au rechargement. Un bug qui ne
                // vivait que dans l'état local : les plus déroutants.
                const existing = racks.find(rack => rack.id === saved.id);

                if (existing) {
                    existing.x = saved.x;
                    existing.y = saved.y;
                } else {
                    // Première pose : les infos complémentaires viennent des
                    // data-attributes de l'entrée de liste, jamais du texte
                    // affiché — une donnée d'affichage n'est pas une source.
                    const listItem = document.querySelector(
                        '.rack-pick[data-rack-id="' + rackId + '"]');

                    racks.push({
                        id: saved.id,
                        name: saved.name,
                        x: saved.x,
                        y: saved.y,
                        site: listItem ? listItem.dataset.rackSite : '',
                        location: listItem ? listItem.dataset.rackLocation : '',
                        device_count: listItem ? parseInt(listItem.dataset.rackDevices, 10) : 0,
                        status_value: 'active',
                    });

                    if (listItem) { listItem.remove(); }
                    const counter = document.getElementById('unplaced-count');
                    if (counter) {
                        counter.textContent = document.querySelectorAll('.rack-pick').length;
                    }
                }

                renderMarkers();
                // La baie est posée : on relâche la sélection. Sans ça, chaque
                // clic suivant sur le plan la reposait ailleurs.
                disarm();
                toast(cfg.dataset.labelSaved + ' : ' + saved.name, false);
            })
            .catch(err => toast(cfg.dataset.labelError + ' (' + err.message + ')', true));
    }

    function clearPosition(rackId) {
        post(cfg.dataset.urlClear, { rack_id: rackId })
            .then(() => {
                racks = racks.filter(r => r.id !== rackId);
                renderMarkers();
                // Ici on recharge : la baie doit réapparaître dans la liste des
                // non placées, et c'est le serveur qui fait autorité là-dessus.
                window.location.reload();
            })
            .catch(err => toast(cfg.dataset.labelError + ' (' + err.message + ')', true));
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  Démarrage
    // ═══════════════════════════════════════════════════════════════════════

    // On attend que l'image soit chargée : sans naturalWidth, impossible de
    // calculer l'échelle d'ajustement.
    if (image.complete) {
        fitToViewport();
    } else {
        image.addEventListener('load', fitToViewport);
    }

    renderMarkers();
    window.addEventListener('resize', fitToViewport);
})();
