"""
agent.py
Plantilla oficial de l'agent de control per al repte de la bateria de UPC Sostenible.
Datathon 2026.
"""

class BatteryAgent:
    def __init__(self):
        """Inicialització de l'agent."""
        self.potencia_nominal_kw = 500.0      # Potència màxima de l'inversor (kW)
        self.historial = []                   # Memòria d'hores passades
        self.cost_real_guardat = None         # Cost/CO2 real de l'energia guardada

    def act(self, obs: dict) -> float:
        preu = obs["preu_actual"]
        co2 = obs["co2_actual"]
        preus_24h = obs["preus_properes_24h"]
        co2_24h = obs["co2_properes_24h"]
        soc_kwh = float(obs["soc_kwh"])
        soc = obs["soc_pct"]

        # 1. Estimació del consum net del campus (consum - solar)
        dades_recents = obs["noves_dades_5min"]
        consum_recent = float(dades_recents["ultim_consum_kw"])
        solar_recent = float(dades_recents["ultima_solar_kw"])
        self.historial.append((consum_recent, solar_recent))

        if len(self.historial) >= 24:
            consum_ahir, solar_ahir = self.historial[-23]
            demanda_neta = 0.4 * (consum_recent - solar_recent) + 0.6 * (consum_ahir - solar_ahir)
        else:
            demanda_neta = consum_recent - solar_recent

        # 2. Cost/CO2 en escala fixa (70% CO2 + 30% Preu) per comparar entre dies diferents sense errors
        cost_actual = 0.70 * (co2 / 0.04) + 0.30 * (preu / 0.06)
        costos_24h = [0.70 * (c / 0.04) + 0.30 * (p / 0.06) for c, p in zip(co2_24h, preus_24h)]

        # Finestra de 8 hores per capturar cada mig dia (nit->matí i migdia->vespre)
        costos_8h = costos_24h[:8]
        ord_8h = sorted(costos_8h)
        ord_24h = sorted(costos_24h)
        mitjana_8h = sum(costos_8h) / len(costos_8h)
        mitjana_24h = sum(costos_24h) / len(costos_24h)

        # Inicialitzem el cost de la càrrega inicial (50%) amb el mínim de les primeres 8h
        if self.cost_real_guardat is None:
            self.cost_real_guardat = ord_8h[0]

        consigna = 0.0

        # A) Excedent solar gratuït: sempre val la pena guardar-lo
        if demanda_neta < -5.0 and soc < 0.99:
            consigna = min(500.0, -demanda_neta)

        # B) CÀRREGA: Entre les 4 hores més netes/barates de les properes 8h (per arribar al 100%),
        #    per sota de la mitjana del dia, i amb un pic proper que compensi el 10% de pèrdua
        elif (
            cost_actual < mitjana_24h * 0.98
            and cost_actual <= ord_8h[min(3, len(ord_8h) - 1)]
            and max(costos_24h[:9]) * 0.90 > cost_actual
            and soc < 0.99
        ):
            consigna = 500.0

        # C) DESCÀRREGA: Entre les 5 pitjors hores de les properes 8h (per buidar fins al 0%
        #    sense deixar el 20% atrapat), per sobre de la mitjana local de 8h (mai de matinada!),
        #    i sortint guanyant respecte al cost real amb què vam carregar
        elif (
            cost_actual > mitjana_8h
            and (cost_actual >= ord_8h[max(0, len(ord_8h) - 5)] or cost_actual >= ord_24h[max(0, len(ord_24h) - 8)])
            and cost_actual * 0.90 > self.cost_real_guardat
            and soc > 0.01
        ):
            if demanda_neta > 15.0:
                consigna = -min(500.0, demanda_neta)

        # 3. Clamping exacte igual que el simulador per garantir 0 infraccions
        rendiment_eta = 0.9 ** 0.5
        marge = 0.01
        max_carrega = min(self.potencia_nominal_kw, max(0.0, (2000.0 - soc_kwh - marge) / rendiment_eta))
        max_descarrega = min(self.potencia_nominal_kw, max(0.0, (soc_kwh - marge) * rendiment_eta))

        accio = float(max(-max_descarrega, min(max_carrega, consigna)))

        # Actualitzem el cost/CO2 mitjà real de l'energia guardada dins la bateria
        if accio > 0:
            energia_nova = accio * rendiment_eta
            self.cost_real_guardat = (
                (soc_kwh * self.cost_real_guardat + energia_nova * cost_actual)
                / (soc_kwh + energia_nova)
            )

        return accio
