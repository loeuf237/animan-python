# A03, A04 et A05 — découpage et garanties

Les changements sont présents dans le code source. Ils ne recompilent pas les
APK distribués. Les tests utilisent des fournisseurs et médias contrôlés ; ils
ne prouvent pas l'accès permanent aux sites.

## A03 — Étapes composées et limites de concurrence

`DownloadManagerService` reste la façade compatible avec l'API et les
intégrations. Son implémentation passe d'environ 3 300 à 1 650 lignes. Il compose :

| Composant | Responsabilité et état possédés |
| --- | --- |
| `TransferWorker` | Résolution existante, transferts directs/HLS/myTV, reprise, retries et throttling |
| `MediaPipeline` | Assemblage temporaire HLS/myTV, sous-titres, mux, intégrité ; jobs natifs, verrous et budget média |
| `ExportCoordinator` | Publication native indépendante ; jobs, verrous et budget d'export |
| `DownloadScheduler` | Ordre et admission, références aux workers, places réseau, échéances et arrêt |

Les méthodes historiques délèguent aux composants. Ceux-ci reçoivent encore un
contexte typé `DownloadManagerService` pour conserver les hooks et les contrôles
existants. C'est une extraction progressive par composition ; le remplacement
de ce contexte par des ports minimaux reste un travail de découplage ultérieur.

Le nombre de transferts est réglé par `maxConcurrentDownloads`. Les variables
`ANIMAN_MEDIA_WORKERS` et `ANIMAN_EXPORT_WORKERS`, par défaut à 1, règlent
indépendamment le travail média et la publication. Elles sont lues au démarrage.
Une place réseau est libérée avant assemblage/finalisation : un mux ou un export
lent ne monopolise plus une place de téléchargement. Les sous-titres sont reçus
avant cette libération.

Le permis média/export appartient à la durée réelle du job, pas à celle de son
attente Python. Une annulation conserve le permis et le suivi du worker natif
jusqu'à son retour. Une tâche en attente ou en cours de finalisation ne peut pas
être supprimée ou relancée concurremment. Les fonctions de publication vérifient
pause/annulation avant de publier. Une pause ne tue pas instantanément un appel
FFmpeg/JNI déjà engagé : il peut devoir terminer avant la reprise.

`download_stages/state.py` explicite les transitions légales. L'export conserve
ses propres états, indépendants de l'état du transfert. L'arrêt ferme l'admission,
annule les workers suivis, enregistre les pauses et attend les jobs natifs
restants. Le délai de fermeture gracieuse des connexions HTTP est borné à
10 secondes pour éviter qu'un flux SSE garde le rechargement ouvert indéfiniment.

L'assemblage HLS s'effectue maintenant dans le budget média, hors de la boucle
événementielle. Le chemin myTV publie également depuis un fichier temporaire et
vérifie les longueurs annoncées des morceaux ; une destination existante est
préservée. Les garanties A08 de cache, d'absence d'écrasement et de reprise restent
couvertes par les tests existants.

## A04 — Même sélection, capacités explicites

`source_registry.py` définit un `SourceProvider` structurel pour la recherche,
la fiche et les dernières sorties. `RegisteredSource` associe l'identité, le
service et `SourceCapabilities`. Les services existants n'ont pas à hériter
d'une nouvelle classe. Le registre consulte les extensions actives à chaque
sélection et tient compte des recettes et adaptateurs connus.

La recherche Vue et Jinja, les fiches, les flux et le catalogue utilisent ce
registre. Le watchdog passe par `SourceCatalogueService.provider()`, qui renvoie
le même fournisseur enregistré. Le catalogue garde ses parcours particuliers
de tags, pagination et API ; il utilise la description commune des capacités.

Une source inconnue ou désactivée est refusée. La fiche ne sollicite plus une
autre source silencieusement lorsqu'elle est vide. Une URL n'est rapprochée
d'une source que par un domaine exact ou un vrai sous-domaine, et non par une
simple sous-chaîne. Les résultats annotés ne modifient pas les objets du cache
du fournisseur.

Les vues d'une extension dépendent de ce que la recette ou l'adaptateur permet
réellement : une méthode générique présente ne suffit pas à annoncer un catalogue
ou une vue populaire. `supports_latest: false` est respecté. Le sélecteur de
nouveautés de l'accueil masque les extensions sans cette capacité. Il ne s'agit
pas d'un contrôle de santé : sélecteurs périmés, protection et panne réseau
continuent d'être signalés séparément.

## A05 — Accès SQLite commun et migrations numérotées

`database.py` centralise les connexions applicatives SQLite et ORM : WAL,
`synchronous=NORMAL`, `busy_timeout=5000`, clés étrangères et fermeture garantie.
La lecture immuable d'une base de cookies d'un navigateur externe reste un cas
distinct : cette base n'appartient pas à Animan et n'est jamais migrée.

| Version | Migration |
| --- | --- |
| 1 | Tables du domaine |
| 2 | Identité, vérification et colonnes d'export des téléchargements |
| 3 | Préférences de suivi et conversion des anciennes erreurs d'export |
| 4 | Réglages des sources, extensions, proxy et pool public |

Le journal `schema_migrations` conserve version, nom et date. Un `BEGIN IMMEDIATE`
explicite sérialise les mises à niveau concurrentes et permet de revenir sur le
DDL et les données si une étape échoue. Le journal n'est confirmé qu'avec la
migration. Un historique incomplet, une identité différente ou une version
future inconnue arrête le démarrage au lieu d'altérer la base.

Les services de configuration utilisent la même initialisation et la même
fabrique de connexions. Le service de bibliothèque utilise une unité de travail
ORM qui commit ou rollback et ferme sa session. Lorsqu'une tâche complète est
sauvegardée, sa progression, ses métadonnées d'export et son résultat de suivi
automatique sont enregistrés dans la même transaction. Un échec après l'écriture
de progression ne laisse pas une tâche ou un export partiellement confirmé.

La migration est répétable. Une sauvegarde externe reste conseillée avant tout
retour à une ancienne version : aucune migration descendante destructrice n'est
proposée. Pour une base ouverte en WAL, utiliser l'API de sauvegarde SQLite ou
arrêter l'application avant la copie, plutôt que copier le seul fichier principal.

## Validation et contrôles manuels

Tests dédiés : `test_download_stages.py`, `test_source_registry.py` et
`test_versioned_database.py`. Ils couvrent concurrence et annulation, fermeture
et restauration, les trois sources natives et une extension, les capacités
absentes, la conservation du cache, les migrations répétées sur une copie
ancienne, le rollback réel d'un ALTER TABLE et la transaction tâche/progression.

Une copie de la base réelle a été migrée deux fois : `PRAGMA integrity_check`
renvoie `ok` et les lignes des 8 tables applicatives comparées sont inchangées
(téléchargements, favoris, progression, suivi, paramètres, proxies, extensions
et dépôts). La copie privée et le bilan sans valeurs sensibles se trouvent dans
`build/validation-a03-a05/`, ignoré par Git.

Pour reproduire, utiliser les variables d'isolation indiquées dans le
[guide A06–A08](a06-a08-validation.md), puis lancer `python3 -m pytest -q`,
`npm test --prefix frontend` et `npm run build --prefix frontend`.
Choisir un dossier de test neuf à chaque exécution : les tests historiques de
lots conservent des tâches et la détection de doublons est intentionnelle.

Validation du 20 octobre 2026 : **458 tests Python** et **26 tests frontend**
réussis, compilation TypeScript/Vite réussie. Les deux avertissements de
dépréciation Starlette/AnyIO et l'avertissement de taille de bundle Vite
préexistants subsistent. Les **17 diagrammes** ont été régénérés ; **106 références**
au code et l'archive hors ligne ont été vérifiées.

Le serveur local confirme des budgets média/export à 1, des capacités pour les
12 sources actives, HTTP 404 pour une source inconnue et une lecture locale
HEAD 200 / Range 206 avec les 64 octets demandés. Le schéma OpenAPI ne présente
aucune référence manquante ; ces contrôles n'ont changé l'état d'aucune tâche.

Contrôles manuels recommandés sur une version reconstruite :

1. Avec une seule place réseau, télécharger deux épisodes : le second doit
   commencer pendant la finalisation du premier, avec un seul traitement média
   actif par défaut.
2. Mettre en pause pendant une fusion ; attendre la fin du worker puis reprendre.
   Arrêter et relancer l'application pendant un transfert : la tâche doit revenir
   en pause avec ses données partielles.
3. Désactiver une extension : une nouvelle recherche ciblée doit refuser cette
   source, sans afficher les résultats d'une source native à sa place.
4. Sur Android, tester publication lente, refus SAF et réexport hors ligne. La
   copie locale vérifiée doit rester disponible et aucune reprise concurrente
   ne doit créer de deuxième publication.

Le code Kotlin n'a pas changé dans cette étape. La validation Android sur appareil,
la reconstruction de l'APK et les contrôles de sites réels restent distincts.
