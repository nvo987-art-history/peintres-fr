# Peintres français — NVO987

## Présentation

**Peintres français** est une base de données publique et consultable consacrée aux personnes liées à la peinture française.

Le site est édité par **NVO987 — Culture Visuelle Moderne et Contemporaine** et propose une interface permettant de rechercher et de filtrer les artistes référencés.

Site officiel :

https://peintres-fr.nvo987.eu/

Site de l'éditeur :

https://www.nvo987.fr/

Contact :

contact@nvo987.eu

---

## Objectif du projet

Le projet a pour objectif de proposer une ressource simple, publique et exploitable par les humains comme par les machines concernant les peintres français.

Les données sont principalement issues de **Wikidata** et sont utilisées dans le cadre de la licence **CC0 1.0 Universal** lorsque cette licence s'applique aux données concernées.

Chaque fiche peut notamment contenir :

- le nom de la personne ;
- l'identifiant Wikidata ;
- un lien vers Wikipédia ;
- le site officiel de l'artiste lorsqu'il est disponible.

La base est conçue pour permettre une recherche rapide et une consultation directe des informations disponibles.

---

## Source des données

La source principale des données est :

https://www.wikidata.org/

Les données provenant de Wikidata sont réutilisées conformément aux conditions applicables à Wikidata et à la licence CC0 1.0 Universal.

Licence :

https://creativecommons.org/publicdomain/zero/1.0/

La licence CC0 applicable aux données sources ne signifie pas que l'ensemble du site, son code, sa présentation, ses textes éditoriaux ou sa structure sont placés sous CC0.

---

## Fonctionnement

Le site utilise une interface web statique avec chargement dynamique des données.

Les données principales sont chargées depuis le fichier :

https://peintres-fr.nvo987.eu/painters.json

Le navigateur charge ce fichier puis construit dynamiquement la liste des personnes référencées.

La recherche et les filtres sont exécutés côté client.

Aucun compte utilisateur n'est nécessaire pour consulter la base.
