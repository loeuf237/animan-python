# A10, A12 et A13 — réalisation et validation

Implémentation dans le code source du 20 octobre 2026. Les paquets bureau et APK
installés ne sont pas reconstruits par cette modification.

## A10 — diagnostiquer une panne

Les journaux structurés contiennent des identifiants tâche/source/domaine, une
opération, un statut et des durées. Les transitions de tâche sont mesurées avec une
horloge monotone ; le budget natif mesure également l’attente et la durée réelle du
travail, même si son appelant est annulé. Les appels du registre commun et les
catalogues sont chronométrés. Les messages et traces sont expurgés avant formatage :
URL sans chemin ni paramètres, en-têtes sensibles supprimés, valeurs de secrets
connues masquées. Les cookies sont enregistrés auprès du masque sans être exportés.

`GET /api/diagnostics/export`, local uniquement, produit un JSON sur liste blanche :
version, plateforme, compteurs de tâches et 2 000 événements récents au maximum.
Aucun objet de tâche brut, recette, paramètre proxy, contenu HTTP ou base complète
n’est inclus. Ce tampon en mémoire repart à zéro au redémarrage ; il n’est pas un
historique permanent ni un service de télémétrie distant. Les champs de durée et
d’identification manquants restent absents, aucune valeur n’est inventée.

Test manuel :

1. Ouvrir **Paramètres → Système & Stockage**, sur l’appareil du serveur.
2. Lancer une opération normale, puis **Exporter les diagnostics**.
3. Vérifier le téléchargement du fichier JSON et le message de succès.
4. Vérifier `schemaVersion`, `taskCounts`, les événements, statuts et durées.
5. Vérifier l’absence de cookies, mots de passe, URL vidéo signées et jeton loopback.
6. Une connexion depuis un autre appareil doit recevoir un refus de cet export.

## A12 — reprendre la bonne lecture

La migration 5 ajoute `playback_progress`. La clé est source/série/épisode/version,
et non le nom du fichier ou l’URL signée du média. `taskId` est résolu vers l’identité
originale ; une ancienne tâche sans URL conserve une identité limitée à cette tâche.
`WatchProgress` conserve ses indicateurs vu/téléchargé sans conversion destructive.

Le lecteur sauvegarde au plus toutes les cinq secondes, puis sur pause, fermeture,
changement d’épisode et sortie de page. Le serveur limite aussi les écritures
intermédiaires à une toutes les deux secondes. Session active et séquence croissante
empêchent une requête tardive ou une ancienne fenêtre d’écraser une lecture récente.
La fin remet la prochaine position à zéro ; les positions inférieures à trois secondes
ou à moins de cinq secondes de la fin ne déclenchent pas de reprise.

Qualité, serveur et pistes sont explicites ; les pistes utilisent langue/libellé/type,
pas leur URL temporaire. Le lecteur restaure après réception des métadonnées et
conserve la position au changement de qualité/serveur. Une lecture dont les
métadonnées n’arrivent pas n’écrit pas de fausse position. L’échec de la progression
reste non bloquant et visible. Un arrêt forcé peut perdre les dernières secondes ;
aucun événement de fermeture navigateur n’est garanti par le système.

Test manuel :

1. Lire un épisode VF pendant plus de 30 secondes, mettre en pause et fermer.
2. Le rouvrir : vérifier la reprise au même instant, puis avancer/reculer.
3. Ouvrir le même épisode en VOSTFR : vérifier qu’il ne reprend pas la position VF.
4. Pour un téléchargement possédant son identité complète, ouvrir cette même version
   depuis sa fiche : vérifier la continuité entre lecture locale et distante.
5. Changer qualité/serveur : vérifier la conservation du temps. Désactiver les
   sous-titres ou changer leur langue ; rouvrir et vérifier le choix.
6. Si le média expose plusieurs pistes audio, sélectionner une autre piste, fermer
   puis rouvrir. HLS et les pistes natives exposées par le navigateur sont pris en
   charge ; cela ne fournit pas de nouveaux codecs.
7. Ouvrir le même épisode dans une deuxième fenêtre, avancer puis fermer. La première
   fenêtre doit indiquer que la seconde a repris la lecture et ne pas l’écraser.
8. Passer à l’épisode suivant pendant une résolution lente : l’ancien temps ne doit
   jamais être enregistré pour le nouvel épisode.
9. Terminer un épisode : sa prochaine lecture commence à zéro ; la marque vu reste
   indépendante. Couper temporairement le serveur : l’erreur de sauvegarde reste
   visible sans faire disparaître le lecteur.

## A13 — observer, tester et restaurer une recette

La migration 6 ajoute santé par opération et historique. Chaque observation conserve
cause, code, durée, nombre de résultats, dernière réussite, série d’échecs et révision.
Les annulations de l’utilisateur ne constituent pas des pannes du site. Une liste vide
de recherche ne prouve pas une dérive : une recherche peut légitimement ne rien trouver.
Un catalogue HTML non vide sans éléments attendus signale une incompatibilité
possible de sélecteurs ; une réponse explicitement vide reste distincte.

Les recettes déclarent `schema_version: 1`. Les anciens JSON sont acceptés et versionnés.
Une modification produit une empreinte et une révision ; l’historique garde les vingt
dernières. La restauration valide à nouveau URL/sélecteurs et crée une révision,
sans modifier l’ancienne. Une version de schéma inconnue est signalée et non exécutée.
Les observations d’une ancienne révision ne prétendent pas valider la nouvelle ;
une réponse en vol arrivée après modification est ignorée pour sa santé.

Avant un lot, la syntaxe des sélecteurs est contrôlée et une incompatibilité connue
de la révision courante empêche la mise en file. Une erreur de sélecteur découverte
pendant la résolution échoue immédiatement sans répéter les mêmes essais réseau.
Le test manuel contrôle le catalogue ; la consultation d’une fiche contrôle ses
détails. Il ne s’agit pas d’un contrôle de tous les épisodes ni d’une garantie de
compatibilité future. L’APK Aniyomi n’est toujours pas exécuté en Kotlin/DEX.

Test manuel :

1. **Extensions → Tester** : observer état, date, durée et révision, puis ouvrir un
   catalogue ou lancer une recherche ; l’état doit refléter l’opération effectuée.
2. Lors d’une protection réelle, vérifier le parcours de validation existant ; une
   panne réseau doit avoir un autre message et ne pas devenir « aucun résultat ».
3. **Configurer** : noter la recette et sa révision, modifier un sélecteur valide
   vers un nom absent du site, enregistrer puis tester. L’état doit indiquer les
   éléments attendus manquants, pas une protection.
4. Tenter un lot avec cette incompatibilité observée : vérifier qu’aucune tâche
   n’est créée. Une syntaxe invalide est refusée dès l’enregistrement.
5. Dans **Historique des recettes**, restaurer la révision initiale : vérifier une
   nouvelle révision, le JSON restauré, puis retester le catalogue et les détails.
6. Recharger la page : état et historique restent présents, sans nouveau sondage
   réseau déclenché par la simple ouverture de la liste.

Le corpus `tests/fixtures/extensions` est rédigé à la main et documente des contrats
HTML/JSON sans données utilisateur. Il couvre catalogue normal, sélecteurs déplacés,
état vide et recherche JSON AniWorld. Il ne remplace pas un essai sur le site vivant.

## Résultats de validation

- Tests Python : 489 réussis ; nouveaux tests de confidentialité, progression,
  exclusion des sessions obsolètes, classification, historique et contrôle des lots.
- Interface : 29 tests réussis, dont reprise après métadonnées, conservation du temps
  après changement de qualité, rejet d’événements d’un ancien média et pistes HLS.
- Compilation Vue/TypeScript/Vite : réussie. Avertissement de taille du bloc principal
  toujours présent, sans erreur de compilation.
- Copie de la base réelle à migrations 1–4 : migration vers 1–6 exécutée deux fois,
  `integrity_check=ok`. Valeurs de toutes les anciennes colonnes conservées dans
  les neuf tables : 798 tâches, 679 progressions, 1 favori, 25 découvertes automatiques,
  catalogues et paramètres compris. Original non modifié par ce test.
- Serveur local : nouvelles routes présentes ; 706 tâches terminées et 5 échouées
  toujours disponibles. Export JSON HTTP 200 et téléchargement depuis le bouton
  effectivement vérifiés dans le navigateur.
- Après un blocage du rechargement de développement, serveur relancé sans
  rechargement automatique pour cette session. Contrôles répétés : export 200,
  historique 200, vidéo locale HEAD 200 et Range 206 (64 octets), schéma OpenAPI
  sans référence manquante. Aucun transfert actif lors de cette relance.
- Le contrôle visuel du bouton de diagnostic a réussi ; la navigation ultérieure
  de l’outil navigateur vers Extensions a expiré. Son historique a été vérifié
  par API et tests, sans restaurer une recette réelle de l’utilisateur.
- Android physique et nouvelle compilation APK : non effectués dans ce lot. Rejouer
  ces parcours après intégration dans un nouveau paquet.
