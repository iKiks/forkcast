"""Broadcast line templates in five languages.

Templates only contain numbers through placeholders, so every figure on screen
comes from evidence the Skeptic can check. With an LLM configured, the Narrator
may rewrite the English line; the Skeptic then re-verifies it.
"""
from __future__ import annotations

LANGS = {"en": "English", "fr": "Français", "es": "Español", "pt": "Português", "pcm": "Naijá (Pidgin)"}

T: dict[str, dict[str, tuple[str, str]]] = {
    # kind: {lang: (casual, analyst)}
    "goal": {
        "en": ("GOAL! {player} scores for {team} ({score}). Their chance of winning: {before}% → {after}%.",
               "Goal: {player} [{eid}] · xG {xg} · {speed} km/h. {team} win prob {before}% → {after}% ({delta_s} pts). {n} forks: {fork}%."),
        "fr": ("BUT ! {player} marque pour {team} ({score}). Chances de victoire : {before}% → {after}%.",
               "But : {player} [{eid}] · xG {xg} · {speed} km/h. Probabilité de victoire de {team} {before}% → {after}% ({delta_s} pts). {n} simulations : {fork}%."),
        "es": ("¡GOL! {player} marca para {team} ({score}). Probabilidad de ganar: {before}% → {after}%.",
               "Gol: {player} [{eid}] · xG {xg} · {speed} km/h. Prob. de victoria de {team} {before}% → {after}% ({delta_s} pts). {n} simulaciones: {fork}%."),
        "pt": ("GOL! {player} marca para o {team} ({score}). Chance de vitória: {before}% → {after}%.",
               "Gol: {player} [{eid}] · xG {xg} · {speed} km/h. Prob. de vitória do {team} {before}% → {after}% ({delta_s} pts). {n} simulações: {fork}%."),
        "pcm": ("GOAL! {player} don score for {team} ({score}). Their chance to win don move from {before}% go {after}%.",
                "Goal: {player} [{eid}] · xG {xg} · {speed} km/h. {team} win chance {before}% → {after}% ({delta_s} pts). {n} forks: {fork}%."),
    },
    "chance": {
        "en": ("So close! {player}'s shot is {outcome}. A goal there would have taken {team} from {before}% to {ifgoal}%.",
               "Big chance: {player} [{eid}] · xG {xg} · {outcome}. Value of a goal for {team}: +{swing} win-prob pts."),
        "fr": ("Si près ! La frappe de {player} est {outcome}. Un but aurait fait passer {team} de {before}% à {ifgoal}%.",
               "Grosse occasion : {player} [{eid}] · xG {xg} · {outcome}. Valeur d'un but pour {team} : +{swing} pts de probabilité."),
        "es": ("¡Cerca! El disparo de {player} es {outcome}. Un gol habría llevado a {team} del {before}% al {ifgoal}%.",
               "Ocasión clara: {player} [{eid}] · xG {xg} · {outcome}. Valor del gol para {team}: +{swing} pts de probabilidad."),
        "pt": ("Quase! O chute de {player} é {outcome}. Um gol levaria o {team} de {before}% para {ifgoal}%.",
               "Grande chance: {player} [{eid}] · xG {xg} · {outcome}. Valor do gol para o {team}: +{swing} pts de probabilidade."),
        "pcm": ("E near enter! {player} shoot am but {outcome}. If e enter, {team} for jump from {before}% go {ifgoal}%.",
                "Big chance: {player} [{eid}] · xG {xg} · {outcome}. Goal for add +{swing} win-chance pts for {team}."),
    },
    "turnover": {
        "en": ("{player} wins the ball back for {team}! Their chance of winning: {before}% → {after}%.",
               "Turnover by {player} [{eid}]. Possession goal chance now {threat}%. {team} win prob {before}% → {after}% ({delta_s} pts)."),
        "fr": ("{player} récupère le ballon pour {team} ! Chances de victoire : {before}% → {after}%.",
               "Récupération de {player} [{eid}]. Probabilité de but de la possession : {threat}%. Victoire {team} {before}% → {after}% ({delta_s} pts)."),
        "es": ("¡{player} recupera el balón para {team}! Probabilidad de ganar: {before}% → {after}%.",
               "Recuperación de {player} [{eid}]. Prob. de gol de la posesión: {threat}%. Victoria {team} {before}% → {after}% ({delta_s} pts)."),
        "pt": ("{player} recupera a bola para o {team}! Chance de vitória: {before}% → {after}%.",
               "Recuperação de {player} [{eid}]. Prob. de gol da posse: {threat}%. Vitória {team} {before}% → {after}% ({delta_s} pts)."),
        "pcm": ("{player} collect the ball back for {team}! Their win chance: {before}% → {after}%.",
                "{player} win the ball [{eid}]. Chance say this attack go score: {threat}%. {team} win chance {before}% → {after}% ({delta_s} pts)."),
    },
    "red": {
        "en": ("Red card! {player} is sent off and {team} are down to ten.", "Red card: {player} [{eid}]. {team} play with ten."),
        "fr": ("Carton rouge ! {player} est expulsé, {team} réduit à dix.", "Carton rouge : {player} [{eid}]. {team} à dix."),
        "es": ("¡Tarjeta roja! {player} es expulsado y {team} se queda con diez.", "Roja: {player} [{eid}]. {team} con diez."),
        "pt": ("Cartão vermelho! {player} é expulso e o {team} fica com dez.", "Vermelho: {player} [{eid}]. {team} com dez."),
        "pcm": ("Red card! Ref don send {player} comot and {team} remain ten players.", "Red card: {player} [{eid}]. {team} na ten players now."),
    },
    "record_shot": {
        "en": ("{player} hits it at {speed} km/h, the fastest shot of the match so far.", "Fastest shot so far: {player} [{eid}] · {speed} km/h."),
        "fr": ("{player} frappe à {speed} km/h, la frappe la plus rapide du match jusqu'ici.", "Frappe la plus rapide : {player} [{eid}] · {speed} km/h."),
        "es": ("{player} le pega a {speed} km/h: el disparo más rápido del partido hasta ahora.", "Disparo más rápido: {player} [{eid}] · {speed} km/h."),
        "pt": ("{player} chuta a {speed} km/h, o chute mais rápido da partida até agora.", "Chute mais rápido: {player} [{eid}] · {speed} km/h."),
        "pcm": ("{player} shoot am {speed} km/h, na the fastest shot for this match so far.", "Fastest shot so far: {player} [{eid}] · {speed} km/h."),
    },
    "record_sprint": {
        "en": ("{player} is flying: {speed} km/h, the fastest sprint of the match so far.", "Top sprint so far: {player} [{eid}] · {speed} km/h."),
        "fr": ("{player} s'envole : {speed} km/h, le sprint le plus rapide du match jusqu'ici.", "Sprint le plus rapide : {player} [{eid}] · {speed} km/h."),
        "es": ("{player} vuela: {speed} km/h, el sprint más rápido del partido hasta ahora.", "Sprint más rápido: {player} [{eid}] · {speed} km/h."),
        "pt": ("{player} voa: {speed} km/h, a arrancada mais rápida da partida até agora.", "Arrancada mais rápida: {player} [{eid}] · {speed} km/h."),
        "pcm": ("{player} dey fly: {speed} km/h, na the fastest run for this match so far.", "Fastest run so far: {player} [{eid}] · {speed} km/h."),
    },
    "record_pass": {
        "en": ("What a pass from {player}! Only {succ}% of passes like that find their man.",
               "Hardest pass completed: {player} [{eid}] · difficulty {diff}/100 · success prob {succ}%."),
        "fr": ("Quelle passe de {player} ! Seules {succ}% des passes de ce type arrivent.",
               "Passe la plus difficile : {player} [{eid}] · difficulté {diff}/100 · réussite {succ}%."),
        "es": ("¡Qué pase de {player}! Solo el {succ}% de pases así llegan a destino.",
               "Pase más difícil: {player} [{eid}] · dificultad {diff}/100 · éxito {succ}%."),
        "pt": ("Que passe de {player}! Só {succ}% dos passes assim chegam ao destino.",
               "Passe mais difícil: {player} [{eid}] · dificuldade {diff}/100 · sucesso {succ}%."),
        "pcm": ("See pass from {player}! Only {succ}% of pass like this dey reach.",
                "Hardest pass: {player} [{eid}] · difficulty {diff}/100 · success {succ}%."),
    },
    "control_take": {
        "en": ("{team} have taken control: {share}% of the ball in the last five minutes.",
               "Control index {idx}/100 · {team} {share}% of touches · chain length {chain}."),
        "fr": ("{team} prend le contrôle : {share}% du ballon sur les cinq dernières minutes.",
               "Indice de contrôle {idx}/100 · {team} {share}% des touches · {chain} actions par séquence."),
        "es": ("{team} toma el control: {share}% del balón en los últimos cinco minutos.",
               "Índice de control {idx}/100 · {team} {share}% de toques · {chain} acciones por secuencia."),
        "pt": ("O {team} assume o controle: {share}% da bola nos últimos cinco minutos.",
               "Índice de controle {idx}/100 · {team} {share}% dos toques · {chain} ações por sequência."),
        "pcm": ("{team} don hold the game: {share}% of the ball for the last five minutes.",
                "Control index {idx}/100 · {team} {share}% of touches · chain {chain}."),
    },
    "control_chaos": {
        "en": ("The game has broken open: the ball is changing hands every {every} touches.",
               "Chaos phase: control index {idx}/100 · turnover rate {rate}% · pressure on {press}% of touches."),
        "fr": ("Le match s'emballe : le ballon change de camp toutes les {every} touches.",
               "Phase de chaos : indice {idx}/100 · pertes {rate}% · pression sur {press}% des touches."),
        "es": ("El partido se ha roto: el balón cambia de dueño cada {every} toques.",
               "Fase de caos: índice {idx}/100 · pérdidas {rate}% · presión en {press}% de toques."),
        "pt": ("O jogo ficou aberto: a bola muda de dono a cada {every} toques.",
               "Fase de caos: índice {idx}/100 · perdas {rate}% · pressão em {press}% dos toques."),
        "pcm": ("Game don scatter: ball dey change hand every {every} touches.",
                "Chaos phase: control index {idx}/100 · turnover {rate}% · pressure {press}%."),
    },
    "halftime": {
        "en": ("Half time, {score}. Forkcast outlook: {home} {hw}% · draw {dw}% · {away} {aw}%.",) * 2,
        "fr": ("Mi-temps, {score}. Prévision Forkcast : {home} {hw}% · nul {dw}% · {away} {aw}%.",) * 2,
        "es": ("Descanso, {score}. Pronóstico Forkcast: {home} {hw}% · empate {dw}% · {away} {aw}%.",) * 2,
        "pt": ("Intervalo, {score}. Previsão Forkcast: {home} {hw}% · empate {dw}% · {away} {aw}%.",) * 2,
        "pcm": ("Half time, {score}. Forkcast talk say: {home} {hw}% · draw {dw}% · {away} {aw}%.",) * 2,
    },
    "fulltime": {
        "en": ("Full time: {home} {hs}–{as_} {away}.",
               "Full time {hs}–{as_}. xG {hxg}–{axg}. Biggest moment: {bigplayer} ({bigclock}, {bigdelta} pts)."),
        "fr": ("Fin du match : {home} {hs}–{as_} {away}.",
               "Score final {hs}–{as_}. xG {hxg}–{axg}. Moment clé : {bigplayer} ({bigclock}, {bigdelta} pts)."),
        "es": ("Final: {home} {hs}–{as_} {away}.",
               "Final {hs}–{as_}. xG {hxg}–{axg}. Momento clave: {bigplayer} ({bigclock}, {bigdelta} pts)."),
        "pt": ("Fim de jogo: {home} {hs}–{as_} {away}.",
               "Final {hs}–{as_}. xG {hxg}–{axg}. Lance decisivo: {bigplayer} ({bigclock}, {bigdelta} pts)."),
        "pcm": ("Full time: {home} {hs}–{as_} {away}.",
                "Full time {hs}–{as_}. xG {hxg}–{axg}. Biggest moment: {bigplayer} ({bigclock}, {bigdelta} pts)."),
    },
}

OUTCOME = {
    "saved": {"en": "saved", "fr": "arrêtée", "es": "atajado", "pt": "defendido", "pcm": "goalie save am"},
    "off_target": {"en": "off target", "fr": "non cadrée", "es": "desviado", "pt": "desviado", "pcm": "e miss target"},
    "blocked": {"en": "blocked", "fr": "contrée", "es": "bloqueado", "pt": "bloqueado", "pcm": "dem block am"},
}

CLUB_PREFIX = {
    "good": {"en": "Good news for {club} fans: ", "fr": "Bonne nouvelle pour les supporters de {club} : ",
             "es": "Buenas noticias para la afición de {club}: ", "pt": "Boa notícia para a torcida do {club}: ",
             "pcm": "Na good news for {club} fans: "},
    "bad": {"en": "Worrying for {club} fans: ", "fr": "Inquiétant pour les supporters de {club} : ",
            "es": "Preocupante para la afición de {club}: ", "pt": "Preocupante para a torcida do {club}: ",
            "pcm": "Wahala dey for {club} fans: "},
}

UI = {
    "flourish": "the turning point of the match",
}


def render(kind: str, lang: str, lens: str, values: dict) -> str:
    casual, analyst = T[kind][lang]
    tpl = analyst if lens == "analyst" else casual
    v = dict(values)
    if "outcome_key" in v:
        v["outcome"] = OUTCOME.get(v["outcome_key"], {}).get(lang, v["outcome_key"])
    return tpl.format(**v)


def club_prefix(sentiment: str, lang: str, club: str) -> str:
    if sentiment not in CLUB_PREFIX:
        return ""
    return CLUB_PREFIX[sentiment][lang].format(club=club)


# ---------------------------------------------------------------------- descriptive forecasts
NEED = {"en": ("a goal", "{n} goals"), "fr": ("un but", "{n} buts"), "es": ("un gol", "{n} goles"),
        "pt": ("um gol", "{n} gols"), "pcm": ("one goal", "{n} goals")}

T.update({
    "after_lead": {
        "en": ("{trail} need {need_phrase} in {mins} minutes and come back to draw or win {p_back}% of the time. Most likely finish: {sl} ({slp}%).",
               "{lead} {lw}% · draw {dw}% · {trail} {tw}%. xG still to come {egl}–{egt}. Most likely {sl} ({slp}%), then {sl2} ({slp2}%)."),
        "fr": ("{trail} doit marquer {need_phrase} en {mins} minutes et revient au moins à égalité dans {p_back}% des cas. Score final le plus probable : {sl} ({slp}%).",
               "{lead} {lw}% · nul {dw}% · {trail} {tw}%. Buts attendus d'ici la fin {egl}–{egt}. Le plus probable {sl} ({slp}%), puis {sl2} ({slp2}%)."),
        "es": ("{trail} necesita {need_phrase} en {mins} minutos y empata o gana el {p_back}% de las veces. Resultado más probable: {sl} ({slp}%).",
               "{lead} {lw}% · empate {dw}% · {trail} {tw}%. Goles esperados hasta el final {egl}–{egt}. Lo más probable {sl} ({slp}%), luego {sl2} ({slp2}%)."),
        "pt": ("O {trail} precisa de {need_phrase} em {mins} minutos e empata ou vira em {p_back}% das vezes. Placar final mais provável: {sl} ({slp}%).",
               "{lead} {lw}% · empate {dw}% · {trail} {tw}%. Gols esperados até o fim {egl}–{egt}. Mais provável {sl} ({slp}%), depois {sl2} ({slp2}%)."),
        "pcm": ("{trail} need {need_phrase} inside {mins} minutes; dem dey draw or win {p_back}% of the time. Score wey fit end am pass: {sl} ({slp}%).",
                "{lead} {lw}% · draw {dw}% · {trail} {tw}%. xG wey still dey come {egl}–{egt}. Most likely {sl} ({slp}%), next {sl2} ({slp2}%)."),
    },
    "after_level": {
        "en": ("All square with {mins} minutes left. Next goal: {home} {ngh}% · {away} {nga}% · nobody {ngn}%.",
               "Level, {mins}' left. Next goal {home} {ngh}% / {away} {nga}% / none {ngn}%. Most likely {sl} ({slp}%), then {sl2} ({slp2}%)."),
        "fr": ("Égalité avec {mins} minutes à jouer. Prochain but : {home} {ngh}% · {away} {nga}% · aucun {ngn}%.",
               "Égalité, {mins}' à jouer. Prochain but {home} {ngh}% / {away} {nga}% / aucun {ngn}%. Le plus probable {sl} ({slp}%), puis {sl2} ({slp2}%)."),
        "es": ("Empate con {mins} minutos por jugar. Próximo gol: {home} {ngh}% · {away} {nga}% · ninguno {ngn}%.",
               "Empate, {mins}' por jugar. Próximo gol {home} {ngh}% / {away} {nga}% / ninguno {ngn}%. Lo más probable {sl} ({slp}%), luego {sl2} ({slp2}%)."),
        "pt": ("Tudo igual com {mins} minutos pela frente. Próximo gol: {home} {ngh}% · {away} {nga}% · nenhum {ngn}%.",
               "Empate, {mins}' restantes. Próximo gol {home} {ngh}% / {away} {nga}% / nenhum {ngn}%. Mais provável {sl} ({slp}%), depois {sl2} ({slp2}%)."),
        "pcm": ("Level game, {mins} minutes remain. Who go score next: {home} {ngh}% · {away} {nga}% · nobody {ngn}%.",
                "Level, {mins}' remain. Next goal {home} {ngh}% / {away} {nga}% / none {ngn}%. Most likely {sl} ({slp}%), next {sl2} ({slp2}%)."),
    },
    "forecast_lead": {
        "en": ("{lead} lead {score} and win from here {lw}% of the time. {trail} need {need_phrase} in {mins} minutes, and there is a {p10}% chance of a goal in the next 10. Most likely finish: {sl} ({slp}%).",
               "{lead} {lw}% · draw {dw}% · {trail} {tw}%. xG to come {egl}–{egt}. Goal in next 10': {p10}%. Most likely {sl} ({slp}%), then {sl2} ({slp2}%)."),
        "fr": ("{lead} mène {score} et gagne {lw}% du temps à partir d'ici. {trail} doit marquer {need_phrase} en {mins} minutes ; {p10}% de chances d'un but dans les 10 prochaines. Le plus probable : {sl} ({slp}%).",
               "{lead} {lw}% · nul {dw}% · {trail} {tw}%. Buts attendus {egl}–{egt}. But dans les 10' : {p10}%. Le plus probable {sl} ({slp}%), puis {sl2} ({slp2}%)."),
        "es": ("{lead} gana {score} y se lleva el partido el {lw}% de las veces desde aquí. {trail} necesita {need_phrase} en {mins} minutos; hay un {p10}% de que caiga un gol en los próximos 10. Lo más probable: {sl} ({slp}%).",
               "{lead} {lw}% · empate {dw}% · {trail} {tw}%. Goles esperados {egl}–{egt}. Gol en los próximos 10': {p10}%. Lo más probable {sl} ({slp}%), luego {sl2} ({slp2}%)."),
        "pt": ("O {lead} vence por {score} e ganha daqui em {lw}% das vezes. O {trail} precisa de {need_phrase} em {mins} minutos; há {p10}% de chance de gol nos próximos 10. Mais provável: {sl} ({slp}%).",
               "{lead} {lw}% · empate {dw}% · {trail} {tw}%. Gols esperados {egl}–{egt}. Gol nos próximos 10': {p10}%. Mais provável {sl} ({slp}%), depois {sl2} ({slp2}%)."),
        "pcm": ("{lead} dey lead {score} and dem dey win from here {lw}% of the time. {trail} need {need_phrase} inside {mins} minutes; chance of goal for the next 10 na {p10}%. Score wey fit end am pass: {sl} ({slp}%).",
                "{lead} {lw}% · draw {dw}% · {trail} {tw}%. xG wey still dey come {egl}–{egt}. Goal for next 10': {p10}%. Most likely {sl} ({slp}%), next {sl2} ({slp2}%)."),
    },
    "forecast_level": {
        "en": ("Still {score} with {mins} minutes left. {fav} edge it, winning {fw}% of the time from here, and there is a {p10}% chance of a goal in the next 10. Most likely finish: {sl} ({slp}%).",
               "{home} {hw}% · draw {dw}% · {away} {aw}%. xG to come {egh}–{ega}. Goal in next 10': {p10}%. Most likely {sl} ({slp}%), then {sl2} ({slp2}%)."),
        "fr": ("Toujours {score} à {mins} minutes de la fin. {fav} a l'avantage et gagne {fw}% du temps ; {p10}% de chances d'un but dans les 10 prochaines. Le plus probable : {sl} ({slp}%).",
               "{home} {hw}% · nul {dw}% · {away} {aw}%. Buts attendus {egh}–{ega}. But dans les 10' : {p10}%. Le plus probable {sl} ({slp}%), puis {sl2} ({slp2}%)."),
        "es": ("Sigue {score} con {mins} minutos por jugar. {fav} tiene ventaja y gana el {fw}% de las veces; hay un {p10}% de que caiga un gol en los próximos 10. Lo más probable: {sl} ({slp}%).",
               "{home} {hw}% · empate {dw}% · {away} {aw}%. Goles esperados {egh}–{ega}. Gol en los próximos 10': {p10}%. Lo más probable {sl} ({slp}%), luego {sl2} ({slp2}%)."),
        "pt": ("Ainda {score} com {mins} minutos pela frente. O {fav} leva vantagem e vence em {fw}% das vezes; há {p10}% de chance de gol nos próximos 10. Mais provável: {sl} ({slp}%).",
               "{home} {hw}% · empate {dw}% · {away} {aw}%. Gols esperados {egh}–{ega}. Gol nos próximos 10': {p10}%. Mais provável {sl} ({slp}%), depois {sl2} ({slp2}%)."),
        "pcm": ("E still be {score}, {mins} minutes remain. {fav} get small edge, dem dey win {fw}% of the time; chance of goal for the next 10 na {p10}%. Score wey fit end am pass: {sl} ({slp}%).",
                "{home} {hw}% · draw {dw}% · {away} {aw}%. xG wey still dey come {egh}–{ega}. Goal for next 10': {p10}%. Most likely {sl} ({slp}%), next {sl2} ({slp2}%)."),
    },
    "chance_more": {
        "en": ("Chances like that go in {xgp}% of the time.",) * 2,
        "fr": ("Ce genre d'occasion finit au fond {xgp}% du temps.",) * 2,
        "es": ("Ocasiones así terminan en gol el {xgp}% de las veces.",) * 2,
        "pt": ("Chances assim viram gol {xgp}% das vezes.",) * 2,
        "pcm": ("Chance like this dey enter {xgp}% of the time.",) * 2,
    },
    "turnover_more": {
        "en": ("This attack now ends in a goal {threat}% of the time, {mult}× an average possession.",) * 2,
        "fr": ("Cette attaque se termine désormais par un but {threat}% du temps, {mult}× une possession moyenne.",) * 2,
        "es": ("Este ataque acaba en gol el {threat}% de las veces, {mult}× una posesión media.",) * 2,
        "pt": ("Este ataque termina em gol {threat}% das vezes, {mult}× uma posse média.",) * 2,
        "pcm": ("This attack fit end for goal {threat}% of the time, {mult}× normal attack.",) * 2,
    },
    "record_distance": {
        "en": ("{player} has covered {km} km, more than anyone on the pitch.", "Distance leader: {player} [{eid}] · {km} km · top speed {top} km/h."),
        "fr": ("{player} a déjà parcouru {km} km, plus que quiconque sur le terrain.", "Plus grande distance : {player} [{eid}] · {km} km · pointe à {top} km/h."),
        "es": ("{player} ya ha recorrido {km} km, más que nadie en el campo.", "Más distancia: {player} [{eid}] · {km} km · punta de {top} km/h."),
        "pt": ("{player} já percorreu {km} km, mais do que qualquer um em campo.", "Maior distância: {player} [{eid}] · {km} km · pico de {top} km/h."),
        "pcm": ("{player} don run {km} km, pass everybody for the pitch.", "Distance leader: {player} [{eid}] · {km} km · top speed {top} km/h."),
    },
})


def render_story(kind: str, lang: str, lens: str, values: dict) -> str:
    """Render a forecast template, filling the language's 'need N goals' phrase."""
    v = dict(values)
    if "need" in v:
        one, many = NEED[lang]
        v["need_phrase"] = one if int(v["need"]) == 1 else many.format(n=v["need"])
    return render(kind, lang, lens, v)

T["forecast_draw"] = {
    "en": ("Still {score} with {mins} minutes left, and a draw is now the likeliest result at {dw}%. There is a {p10}% chance of a goal in the next 10. Next goal: {home} {ngh}% · {away} {nga}%.",
           T["forecast_level"]["en"][1]),
    "fr": ("Toujours {score} à {mins} minutes de la fin, et le nul est désormais le résultat le plus probable ({dw}%). {p10}% de chances d'un but dans les 10 prochaines. Prochain but : {home} {ngh}% · {away} {nga}%.",
           T["forecast_level"]["fr"][1]),
    "es": ("Sigue {score} con {mins} minutos por jugar y el empate ya es el resultado más probable ({dw}%). Hay un {p10}% de que caiga un gol en los próximos 10. Próximo gol: {home} {ngh}% · {away} {nga}%.",
           T["forecast_level"]["es"][1]),
    "pt": ("Ainda {score} com {mins} minutos pela frente, e o empate já é o resultado mais provável ({dw}%). Há {p10}% de chance de gol nos próximos 10. Próximo gol: {home} {ngh}% · {away} {nga}%.",
           T["forecast_level"]["pt"][1]),
    "pcm": ("E still be {score}, {mins} minutes remain, and draw na the result wey fit happen pass now ({dw}%). Chance of goal for next 10 na {p10}%. Who go score next: {home} {ngh}% · {away} {nga}%.",
            T["forecast_level"]["pcm"][1]),
}
T["after_draw"] = T["after_level"]
