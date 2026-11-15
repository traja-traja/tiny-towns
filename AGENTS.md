# Tiny Towns – pokyny projektu

Projekt sdílí renderer Izomapy pro Velešín a České Budějovice. Nejdřív čti `docs/MULTI_CITY.md` a `docs/UPDATES.md`, potom původní pokyny níže.

- Vstupy měst patří do `cities/<slug>/`; sestavení obsluhuje `scripts/towns.py`. Neupravuj generované kopie v `.work/`.
- Zachovej úplné pokrytí hranice obce a rozšíření kolem hradu; zkušební výřez označuj jako výřez, ne hotovou mapu.
- Vlastní geometrii a městská data drž odděleně od rendereru, aby šla později použít v živé 3D mapě. Animace aut není kalibrovaný dopravní model.
- U většího množství samostatných úloh rozděl práci mezi agenty; model a rozsah uvažování zvol podle náročnosti. Přiděl každému vlastní soubory, aby si nepřepisovali změny.

---

# Návod pro AI agenta

Celý návod je v [CLAUDE.md](CLAUDE.md). Platí pro libovolného agenta (Claude Code, Codex…).
