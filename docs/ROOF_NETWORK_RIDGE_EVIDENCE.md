# Evidence hřebenů a zachování křídel — 4.13.3

Datum: 2026-11-17. Obecná oprava rozhodování bez výjimek podle adres.

## Proč předchozí oprava změnila tvar

Lokální měření šířek z 4.13.2 odstranilo přehnaně široké obálky křídel. Současně ale skokový trest za posun hřebene přes 2 % šířky znevýhodnil i střechu s pouze malým rozdílem protějších sklonů. Vyhrál dříve přítomný kandidát U, jehož dodatečné větve neměly dostatečnou oporu jako skutečné hřebeny. Nešlo o chybu zobrazení.

Při následné opravě skóre se projevila další slabina: preference menšího počtu rovin dokázala vymazat kratší křídlo, protože jeho zhoršení se schovalo v průměru celého domu. Proto se přidává lokální ochrana shody s body.

## Co se mění

Lokální měření šířek zůstává. Trest za asymetrii je nově plynulý podle rozdílu protějších sklonů: do 5° bez trestu, mezi 5° a 25° plynulý nárůst, nad 25° plná penalizace 0,15 m ve skóre. Hřeben se nadále přizpůsobuje bodům; není vynucena přesná zrcadlová symetrie. Parametry: paired_slope_tolerance_deg, paired_slope_full_penalty_deg a paired_asymmetry_penalty_m/paired_prefer_symmetric.

U kandidátů U/O již nestačí podobnost několika bodů s blízkou plochou. Každá větev z již používaných rastrových buněk dokládá:

- nejméně 8 buněk ve výšce hřebene, s tolerancí 0,6 m;
- robustní podloženou délku alespoň 3 m a 35 % viditelné délky čáry v půdorysu;
- alespoň 2 po sobě jdoucí úseky dlouhé 1,5 m s měřeným poklesem nejméně 0,12 m na obě strany; nejméně 50 % porovnatelných úseků musí pokles potvrdit.

Pás hřebene je široký 0,6 m na každou stranu, boční podpora se hledá dále do 2,5 m. Body do 0,8 m od hranice půdorysu se pro tuto evidenci ignorují kvůli sousedním stavbám. Zdrojové body ani zobrazení se nemění. Úzká střecha nebo řídká data mohou způsobit nejistotu: nepodložená větev dostává měkkou penalizaci 0,10 m, nikoli tvrdé odstranění celé rodiny.

Jde o lehkou kontrolu buněk, nikoli o 30 analytických profilů v HTML. Analytické profily zůstávají oddělené a vypnuté v mapovém režimu. Kontrolu lze vypnout scoring.network_branch_evidence; rozměry a váhy jsou v scoring.network_*. Metadata branch_support.ridge_evidence obsahují délku, počet buněk, poklesy, důvody nejistoty a penalizaci.

### Ochrana podloženého křídla

Kandidáti s menším počtem ploch se porovnají také na každém podloženém křídle zvlášť, v jeho vlastní ploše mimo překryv s ostatními křídly. Vynechá se pás 0,8 m od hranice domu a vyžaduje se nejméně 8 buněk. Přípustné zhoršení je stejné jako pro celý objekt: max_simplification_data_error_increase_m = 0,10 m. Kandidát, který limit překročí, nedostane přednost jen za menší počet rovin. Stále zůstává záložní možností při neplatné geometrii lepšího kandidáta.

Vypínač: scoring.protect_wing_fit; parametry wing_fit_min_cells a wing_fit_inset_m. Číselné důvody ukládá diagnostics.wing_fit_simplification_guard a záznam jednotlivého kandidáta. Pravidlo nemění rozdělení objemů ani nepředepisuje typ střechy konkrétní adrese.

### Stejná evidence při rozhodování o objemech

Výběr mezi celým domem a podélnými řezy nově přenáší také support_penalty_m vybraných střech. U více objemů jde o průměr vážený plochou jejich půdorysů, nikoli o součet. Tím rozdělení objektu nemůže obejít nejistotu jeho dílčích střech. Dosavadní penalizace dalšího objemu i tolerance ponechání celku zůstávají. Vypínač scoring.volume_inherit_support_penalty, metadata scores.*.roof_support_penalty_m. Přísné rozdělení z 2D proporcí se nemění.

## Ověření

52 cílených testů prošlo za 3,173 s: ridge_evidence, ridge_network, paired_ridges, connected_wings, oblique_wings, eave_simplification, point_fit_simplification, wing_fit_simplification a batch. Testují skutečné U/okruhy, rovinu, jednostranný sklon, izolované body, okrajový šum, rotaci, malé odchylky sklonů a zachování podloženého křídla při zjednodušování.

Přegenerovává se pouze Jírovcova 1449/25 do roof-v4133-jirovcova-ridge-evidence-final. Levé srovnání stále roof-v410-review-inputs-54. Vizuálně kontroluje Pavel. Žádný plošný přepočet měst.

Mezivýstupy roof-v4133-jirovcova-ridge-evidence a roof-v4133-jirovcova-ridge-evidence-2 vznikly před dokončením návazných kontrol křídel a objemů a nejsou finální opravené reporty.

Dokončeno: jeden objem, dvě spojená sedlová křídla (4 roviny), hřeben 12,9948 m a okapová reference 10,3266 m nad lokální nulou. Protější sklony jednotlivých křídel se liší o 2,29° a 2,57°; nejde o vynucenou přesnou symetrii. Uzavřená síť, bez otevřených hran či vnitřních výškových schodů. Výpočet střechy 11,290 s, celá dávka 14,517 s. Levá geometrie přesně shodná s pevným základem, HTTP 200. Optické posouzení neprováděno. Následných 20 testů objemů a křídel prošlo za 0,133 s.
