# DomoLink-Tado-Light 🍃

[![HACS Validation](https://img.shields.io/badge/HACS-Custom%20%26%20Default-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-Calculated-green.svg?style=flat-square)](https://developers.home-assistant.io/docs/creating_integration_manifest/#iot-class)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

**DomoLink-Tado-Light** est un compagnon intelligent **100 % local et hors-ligne** pour vos thermostats de chauffage et climatisation sous Home Assistant (en particulier avec l'intégration officielle Tado).

Contrairement aux intégrations cloud complètes, cette version **Light** ne se connecte pas aux serveurs distants : elle tire parti de vos entités `climate.*` existantes et les enrichit d'analyses physiques avancées, de gestion de confort en un clic, et d'automatisations locales intelligentes.

---

## ✨ Pourquoi DomoLink-Tado-Light ?

| Fonctionnalité | Intégration Officielle Tado | DomoLink-Tado-Light |
| :--- | :---: | :---: |
| Connexion Cloud Tado | ✅ Obligatoire | ❌ Aucun appel API (100% Hors-ligne) |
| Gestion des sondes d'ambiance externes | ❌ Non supporté | ✅ Association par pièce (Zigbee / BLE) |
| Calculs physiques (Point de rosée, Humidité absolue) | ❌ Non | ✅ Magnuss-Tetens & Formules thermo-dynamiques |
| Alerte & Indice de risque de moisissure | ❌ Non | ✅ Normal, Faible, Modéré, Élevé |
| Conseil d'aération intelligent | ❌ Basique payant | ✅ Différentiel hydrique intérieur / extérieur |
| Coupure automatique sur fenêtre ouverte | ⚠️ Abonnement payant | ✅ Gratuit avec vos capteurs magnétiques |
| Boutons globaux (Boost 1-clic, Reprise planning, Tout éteindre) | ❌ Non | ✅ Actions unifiées prêtes à l'emploi |
| Interrupteur Mode Éco Global | ❌ Non | ✅ 1 clic pour basculer toute la maison |
| Préchauffage adaptatif local (Early Start) | ❌ Cloud propriétaire | ✅ Apprentissage de l'inertie thermique (°C/h) |

---

## 🚀 Fonctionnalités Détaillées

### 1. 🌡️ Sondes d'ambiance externes & Écart réel
Les têtes thermostatiques de radiateur mesurent la température au contact immédiat de la source de chaleur, ce qui fausse souvent la régulation.
DomoLink-Tado-Light vous permet d'associer un thermomètre externe (placé au centre de la pièce) pour :
* Mesurer la vraie température d'ambiance.
* Calculer en temps réel l'écart consigne / ambiance (`sensor.<piece>_ecart_consigne_ambiance`).

### 2. 💧 Physique du bâtiment & Climat intérieur
Calculs exécutés localement et mis à jour en temps réel :
* **Point de rosée (`°C`)** : Température de condensation de l'air.
* **Humidité absolue (`g/m³`)** : Masse réelle d'eau présente dans l'air.
* **Risque de moisissure** : Indice 4 niveaux (`normal`, `low`, `medium`, `high`) avec capteur binaire d'alerte.
* **Conseil d'aération** : Compare la teneur en eau intérieure et extérieure pour vous indiquer si aérer va assécher ou humidifier votre pièce.

### 3. 🪟 Protection fenêtres ouvertes (100% Locale)
Associez n'importe quel capteur de contact de porte/fenêtre (`binary_sensor.*`) :
* Dès l'ouverture de la fenêtre, le thermostat de la pièce est basculé sur `OFF` (hors-gel).
* À la fermeture, la programmation ou la consigne précédente est automatiquement restaurée.

### 4. ⚡ Boutons de confort & Services 1-clic
* **Reprendre programmation partout** : Rétablit le mode `AUTO` sur l'ensemble de vos thermostats.
* **Tout éteindre (Hors-gel)** : Éteint tous les thermostats d'un seul geste.
* **Boost Intelligent** : Passe une pièce ou toute la maison à une consigne de confort temporaire (ex: 21.5 °C pendant 30 min) avec minuterie de fin automatique.
* **Interrupteur Mode Éco Global** : Bascule toute la maison à votre consigne économique d'absence (ex: 17 °C) et rétablit le planning à la désactivation.

---

## 📦 Installation

### Via HACS (Recommandé)
1. Ouvrez **HACS** dans votre Home Assistant.
2. Cliquez sur les 3 points en haut à droite > **Dépôts personnalisés** (*Custom repositories*).
3. Ajoutez l'URL de votre dépôt GitHub et choisissez la catégorie **Intégration**.
4. Recherchez **DomoLink-Tado-Light**, cliquez sur **Télécharger** et redémarrez Home Assistant.

### Installation Manuelle
1. Téléchargez le dossier `custom_components/domolink_tado_light`.
2. Déposez-le dans le répertoire `config/custom_components/` de votre Home Assistant.
3. Redémarrez Home Assistant.

---

## ⚙️ Configuration

1. Rendez-vous dans **Paramètres** > **Appareils et services** > **Ajouter une intégration**.
2. Recherchez **DomoLink-Tado-Light**.
3. Définissez vos sondes extérieures (température et humidité) ainsi que vos consignes Éco et Boost par défaut.
4. Ajoutez vos pièces en sélectionnant l'entité `climate.*` correspondante et vos capteurs d'ambiance.
5. Vous pouvez à tout moment ajouter ou modifier des pièces via le bouton **Configurer** de l'intégration.

---

## 📄 Licence
Ce projet est sous licence [MIT](LICENSE).
Auteur : **J.F. Lavigne (SocrateMobile)**
