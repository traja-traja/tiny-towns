# Tiny Towns – pokyny projektu

Projekt sdílí renderer Izomapy pro Velešín a České Budějovice. Nejdřív čti `docs/MULTI_CITY.md` a `docs/UPDATES.md`, potom původní pokyny níže.

- Zkratka **ČB** v komunikaci a dokumentaci znamená **České Budějovice** (`ceske-budejovice`). Plánované úkoly a nápady zapisuj do `docs/TODO.md`.
- Vstupy měst patří do `cities/<slug>/`; sestavení obsluhuje `scripts/towns.py`. Neupravuj generované kopie v `.work/`.
- Zachovej úplné pokrytí hranice obce a rozšíření kolem hradu; zkušební výřez označuj jako výřez, ne hotovou mapu.
- Vlastní geometrii a městská data drž odděleně od rendereru, aby šla později použít v živé 3D mapě. Animace aut není kalibrovaný dopravní model.
- U většího množství samostatných úloh rozděl práci mezi agenty; model a rozsah uvažování zvol podle náročnosti. Přiděl každému vlastní soubory, aby si nepřepisovali změny.

- Po každém menším funkčním kroku vytvoř samostatný commit s relevantním ověřením. Neodkládej zálohu algoritmu až na několik dalších verzí; samotný seznam připravených souborů není commit. Pokud je zápis do Git blokovaný, výslovně uveď, že commit nevznikl, a ulož úplný obsah změn do obnovitelného snapshotu.

---

# Návod pro AI agenta

Celý návod je v [CLAUDE.md](CLAUDE.md). Platí pro libovolného agenta (Claude Code, Codex…).
