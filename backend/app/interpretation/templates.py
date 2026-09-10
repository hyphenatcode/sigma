"""Deterministic Turkish interpretation templates (§3.6).

Two jobs:

1. They are the *constraint* on the LLM. The system prompt hands the model the
   template for the test at hand and tells it to phrase that sentence and
   nothing else.
2. They are the *fallback*. When the §3.6 numeric-token validation rejects the
   generated text, the report is rendered from here instead, with no LLM
   involved. That path must always produce publishable Turkish prose, because
   it is what the user sees whenever the model misbehaves.

Every number in these templates comes from the payload through the APA
formatters, so the fallback text passes its own validator by construction.
"""

from __future__ import annotations

from typing import Any, Optional

from app.apa.formatting import fmt, fmt_df, fmt_p, fmt_statistic

#: How a p-value is phrased inline: "p < .001" has no equals sign.
def _p_clause(p_value: Optional[float]) -> str:
    rendered = fmt_p(p_value)
    return f"p {rendered}" if rendered.startswith("<") else f"p = {rendered}"


def _significance(payload: dict[str, Any]) -> str:
    return (
        "istatistiksel olarak anlamlı"
        if payload.get("is_significant") else
        "istatistiksel olarak anlamlı olmayan"
    )


def _descriptive_clause(group: dict[str, Any]) -> str:
    """'Deney (M = 84.00, SS = 5.01)'"""
    parts = []
    if group.get("mean") is not None:
        parts.append(f"M = {fmt(group['mean'])}")
    if group.get("sd") is not None:
        parts.append(f"SS = {fmt(group['sd'])}")
    detail = f" ({', '.join(parts)})" if parts else ""
    return f"{group['label']}{detail}"


def _effect_clause(payload: dict[str, Any], symbol: str) -> str:
    effect = payload.get("effect_size")
    if not effect:
        return ""
    value = fmt_statistic(effect["metric"], effect["value"])
    return (
        f" Etki büyüklüğü {effect['band_label_tr']} düzeydedir "
        f"({symbol} = {value})."
    )


def _substitution_clause(payload: dict[str, Any]) -> str:
    note = payload.get("substitution_note_tr")
    return f" {note}" if note else ""


def _direction(groups: list[dict[str, Any]], key: str = "mean") -> Optional[str]:
    """Which group scored higher — the '{yön}' slot of the §3.6 template."""
    usable = [g for g in groups if g.get(key) is not None]
    if len(usable) < 2:
        return None
    highest = max(usable, key=lambda g: g[key])
    lowest = min(usable, key=lambda g: g[key])
    if highest[key] == lowest[key]:
        return None
    return highest["label"]


# ---------------------------------------------------------------------------
# One renderer per analysis type
# ---------------------------------------------------------------------------

def _independent_t(payload: dict[str, Any]) -> str:
    groups = payload["group_descriptives"]
    g1, g2 = groups[0], groups[1]
    stats, df = payload["statistics"], payload["df"]

    sentence = (
        f"{_descriptive_clause(g1)} ile {_descriptive_clause(g2)} grupları arasında "
        f"{_significance(payload)} bir fark bulunmuştur, "
        f"t({fmt_df(df.get('df'))}) = {fmt(stats.get('t'))}, {_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        winner = _direction(groups)
        if winner:
            sentence += f" Fark {winner} grubu lehinedir."
        sentence += _effect_clause(payload, "Cohen's d")
    return sentence + _substitution_clause(payload)


def _paired_t(payload: dict[str, Any]) -> str:
    groups = payload["group_descriptives"]
    g1, g2 = groups[0], groups[1]
    stats, df = payload["statistics"], payload["df"]

    sentence = (
        f"Katılımcıların {_descriptive_clause(g1)} ve {_descriptive_clause(g2)} "
        f"ölçümleri arasında {_significance(payload)} bir fark bulunmuştur, "
        f"t({fmt_df(df.get('df'))}) = {fmt(stats.get('t'))}, {_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        winner = _direction(groups)
        if winner:
            sentence += f" {winner} ölçümünde elde edilen puanlar daha yüksektir."
        sentence += _effect_clause(payload, "Cohen's d")
    return sentence + _substitution_clause(payload)


def _anova(payload: dict[str, Any]) -> str:
    stats, df = payload["statistics"], payload["df"]
    labels = ", ".join(g["label"] for g in payload["group_descriptives"])

    sentence = (
        f"{labels} grupları arasında {_significance(payload)} bir farklılık "
        f"bulunmuştur, F({fmt_df(df.get('df_between'))}, {fmt_df(df.get('df_within'))}) = "
        f"{fmt(stats.get('F'))}, {_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        sentence += _effect_clause(payload, "η²")
        # TODO(spec-gap): §3.3/§3.4 do not specify a post-hoc procedure (Tukey,
        # Bonferroni, Games-Howell) for a significant omnibus test, so we state
        # that the omnibus test does not identify which pairs differ rather
        # than running an unspecified post-hoc test.
        sentence += (
            " Bu bulgu, farkın hangi gruplar arasında olduğunu göstermez; "
            "ikili karşılaştırmalar (post-hoc) bu sürümde raporlanmamaktadır."
        )
    return sentence + _substitution_clause(payload)


def _mann_whitney(payload: dict[str, Any]) -> str:
    groups = payload["group_descriptives"]
    g1, g2 = groups[0], groups[1]
    stats = payload["statistics"]

    def rank_clause(group: dict[str, Any]) -> str:
        rank = group.get("mean_rank")
        return (
            f"{group['label']} (sıra ortalaması = {fmt(rank)})"
            if rank is not None else group["label"]
        )

    sentence = (
        f"{rank_clause(g1)} ve {rank_clause(g2)} grupları arasında "
        f"{_significance(payload)} bir fark bulunmuştur, "
        f"U = {fmt(stats.get('U'))}, z = {fmt(stats.get('z'))}, "
        f"{_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        winner = _direction(groups, key="mean_rank")
        if winner:
            sentence += f" Sıra ortalamaları {winner} grubu lehine daha yüksektir."
        sentence += _effect_clause(payload, "r")
    return sentence + _substitution_clause(payload)


def _wilcoxon(payload: dict[str, Any]) -> str:
    groups = payload["group_descriptives"]
    stats = payload["statistics"]
    sentence = (
        f"Katılımcıların {groups[0]['label']} ve {groups[1]['label']} ölçümleri "
        f"arasında {_significance(payload)} bir fark bulunmuştur, "
        f"W = {fmt(stats.get('W'))}, {_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        winner = _direction(groups, key="median")
        if winner:
            sentence += f" {winner} ölçümünde elde edilen puanlar daha yüksektir."
        sentence += _effect_clause(payload, "r")
    return sentence + _substitution_clause(payload)


def _kruskal(payload: dict[str, Any]) -> str:
    stats, df = payload["statistics"], payload["df"]
    labels = ", ".join(g["label"] for g in payload["group_descriptives"])
    sentence = (
        f"{labels} gruplarının sıra ortalamaları arasında {_significance(payload)} "
        f"bir farklılık bulunmuştur, H({fmt_df(df.get('df'))}) = {fmt(stats.get('H'))}, "
        f"{_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        sentence += _effect_clause(payload, "ε²")
    return sentence + _substitution_clause(payload)


def _correlation(payload: dict[str, Any]) -> str:
    stats, df = payload["statistics"], payload["df"]
    is_pearson = payload["analysis_type"] == "pearson_correlation"
    key, symbol = ("r", "r") if is_pearson else ("rho", "ρ")
    variables = payload.get("variables") or [
        g["label"] for g in payload["group_descriptives"]
    ]
    coefficient = stats.get(key, 0.0)
    direction = "pozitif" if coefficient >= 0 else "negatif"
    effect = payload.get("effect_size") or {}
    strength = effect.get("band_label_tr", "")

    return (
        f"{variables[0]} ile {variables[1]} arasında {direction} yönde, "
        f"{strength} düzeyde ve {_significance(payload)} bir ilişki bulunmuştur, "
        f"{symbol}({fmt_df(df.get('df'))}) = {fmt_statistic(key, coefficient)}, "
        f"{_p_clause(payload['p_value'])}."
    ) + _substitution_clause(payload)


def _regression(payload: dict[str, Any]) -> str:
    stats, df = payload["statistics"], payload["df"]
    predictors = payload.get("predictors") or []
    dv = payload.get("dependent_variable", "bağımlı değişken")
    r_squared = stats.get("r_squared", 0.0)

    # Turkish agreement: one predictor takes the singular "değişkeninin",
    # several take the plural "değişkenlerinin".
    predictor_phrase = (
        f"{predictors[0]} değişkeninin" if len(predictors) == 1
        else f"{', '.join(predictors)} değişkenlerinin"
    )
    model_verdict = (
        "istatistiksel olarak anlamlıdır" if payload.get("is_significant")
        else "istatistiksel olarak anlamlı değildir"
    )
    sentence = (
        f"{predictor_phrase} {dv} üzerindeki yordayıcı etkisini belirlemek "
        f"amacıyla kurulan regresyon modeli {model_verdict}, "
        f"F({fmt_df(df.get('df_model'))}, {fmt_df(df.get('df_residual'))}) = "
        f"{fmt(stats.get('F'))}, {_p_clause(payload['p_value'])}. "
        # "%X kadarını" avoids the possessive suffix, whose form would otherwise
        # have to agree with however the final digit is read aloud.
        f"Model, {dv} değişkenindeki varyansın %{fmt(r_squared * 100, 1)} kadarını "
        f"açıklamaktadır (R² = {fmt_statistic('r_squared', r_squared)}, "
        f"düzeltilmiş R² = {fmt_statistic('adjusted_r_squared', stats.get('adjusted_r_squared'))})."
    )

    significant = [c for c in payload.get("coefficients", []) if c["p"] < payload.get("alpha", 0.05)]
    for coefficient in significant:
        sentence += (
            f" {coefficient['predictor']} değişkeni {dv} değişkenini anlamlı düzeyde "
            f"yordamaktadır (B = {fmt(coefficient['b'])}, "
            f"β = {fmt_statistic('beta', coefficient['beta'])}, "
            f"{_p_clause(coefficient['p'])})."
        )
    return sentence + _substitution_clause(payload)


def _chi_square(payload: dict[str, Any]) -> str:
    stats, df = payload["statistics"], payload["df"]
    variables = payload.get("variables", ["Değişken 1", "Değişken 2"])
    sentence = (
        f"{variables[0]} ile {variables[1]} arasında {_significance(payload)} "
        f"bir ilişki bulunmuştur, "
        f"χ²({fmt_df(df.get('df'))}, N = {payload['n_total']}) = "
        f"{fmt(stats.get('chi2'))}, {_p_clause(payload['p_value'])}."
    )
    if payload.get("is_significant"):
        effect = payload.get("effect_size") or {}
        sentence += (
            f" İlişkinin gücü {effect.get('band_label_tr', '')} düzeydedir "
            f"(Cramér's V = {fmt_statistic('cramers_v', effect.get('value'))})."
        )
    return sentence + _substitution_clause(payload)


def _cronbach(payload: dict[str, Any]) -> str:
    stats = payload["statistics"]
    effect = payload.get("effect_size") or {}
    n_items = int(stats.get("n_items", 0))
    return (
        f"Ölçeğin {n_items} maddeden oluşan formunun iç tutarlılık güvenirlik "
        f"katsayısı Cronbach α = {fmt_statistic('alpha', stats.get('alpha'))} olarak "
        f"hesaplanmıştır (n = {payload['n_total']}). Bu değer, ölçeğin güvenirliğinin "
        f"{effect.get('band_label_tr', '')} düzeyde olduğunu göstermektedir."
    )


RENDERERS = {
    "independent_t_test": _independent_t,
    "welch_t_test": _independent_t,
    "paired_t_test": _paired_t,
    "one_way_anova": _anova,
    "welch_anova": _anova,
    "mann_whitney_u": _mann_whitney,
    "wilcoxon_signed_rank": _wilcoxon,
    "kruskal_wallis": _kruskal,
    "pearson_correlation": _correlation,
    "spearman_correlation": _correlation,
    "simple_linear_regression": _regression,
    "multiple_linear_regression": _regression,
    "chi_square_independence": _chi_square,
    "cronbachs_alpha": _cronbach,
}


#: Shown to the LLM as the shape it must fill. Kept close to the §3.6 example.
PROMPT_TEMPLATES = {
    "independent_t_test": (
        "{grup1} (M = {m1}, SS = {ss1}) ile {grup2} (M = {m2}, SS = {ss2}) grupları "
        "arasında {anlamlılık} bir fark bulunmuştur, t({sd}) = {t}, p = {p}. "
        "Fark {lehte_grup} grubu lehinedir. Etki büyüklüğü {etki_yorumu} düzeydedir "
        "(Cohen's d = {d})."
    ),
    "welch_t_test": (
        "{grup1} (M = {m1}, SS = {ss1}) ile {grup2} (M = {m2}, SS = {ss2}) grupları "
        "arasında {anlamlılık} bir fark bulunmuştur, t({sd}) = {t}, p = {p}. "
        "Etki büyüklüğü {etki_yorumu} düzeydedir (Cohen's d = {d})."
    ),
    "paired_t_test": (
        "Katılımcıların {ölçüm1} (M = {m1}, SS = {ss1}) ve {ölçüm2} (M = {m2}, "
        "SS = {ss2}) ölçümleri arasında {anlamlılık} bir fark bulunmuştur, "
        "t({sd}) = {t}, p = {p}. Etki büyüklüğü {etki_yorumu} düzeydedir "
        "(Cohen's d = {d})."
    ),
    "one_way_anova": (
        "{gruplar} grupları arasında {anlamlılık} bir farklılık bulunmuştur, "
        "F({sd1}, {sd2}) = {f}, p = {p}. Etki büyüklüğü {etki_yorumu} düzeydedir "
        "(η² = {eta2})."
    ),
    "welch_anova": (
        "{gruplar} grupları arasında {anlamlılık} bir farklılık bulunmuştur, "
        "F({sd1}, {sd2}) = {f}, p = {p}. Etki büyüklüğü {etki_yorumu} düzeydedir "
        "(η² = {eta2})."
    ),
    "mann_whitney_u": (
        "{grup1} (sıra ortalaması = {sıra1}) ve {grup2} (sıra ortalaması = {sıra2}) "
        "grupları arasında {anlamlılık} bir fark bulunmuştur, U = {u}, z = {z}, "
        "p = {p}, r = {r}."
    ),
    "wilcoxon_signed_rank": (
        "Katılımcıların {ölçüm1} ve {ölçüm2} ölçümleri arasında {anlamlılık} bir "
        "fark bulunmuştur, W = {w}, p = {p}, r = {r}."
    ),
    "kruskal_wallis": (
        "{gruplar} gruplarının sıra ortalamaları arasında {anlamlılık} bir farklılık "
        "bulunmuştur, H({sd}) = {h}, p = {p}, ε² = {eps2}."
    ),
    "pearson_correlation": (
        "{değişken1} ile {değişken2} arasında {yön} yönde, {güç} düzeyde ve "
        "{anlamlılık} bir ilişki bulunmuştur, r({sd}) = {r}, p = {p}."
    ),
    "spearman_correlation": (
        "{değişken1} ile {değişken2} arasında {yön} yönde, {güç} düzeyde ve "
        "{anlamlılık} bir ilişki bulunmuştur, ρ({sd}) = {rho}, p = {p}."
    ),
    "simple_linear_regression": (
        "{yordayıcı} değişkeninin {bağımlı} üzerindeki yordayıcı etkisi için kurulan "
        "regresyon modeli {model_yargısı}, F({sd1}, {sd2}) = {f}, p = {p}. Model, "
        "{bağımlı} değişkenindeki varyansın %{yüzde} kadarını açıklamaktadır (R² = {r2})."
    ),
    "multiple_linear_regression": (
        "{yordayıcılar} değişkenlerinin {bağımlı} üzerindeki yordayıcı etkisi için "
        "kurulan regresyon modeli {model_yargısı}, F({sd1}, {sd2}) = {f}, p = {p}. "
        "Model, {bağımlı} değişkenindeki varyansın %{yüzde} kadarını açıklamaktadır "
        "(R² = {r2})."
    ),
    "chi_square_independence": (
        "{değişken1} ile {değişken2} arasında {anlamlılık} bir ilişki bulunmuştur, "
        "χ²({sd}, N = {n}) = {chi2}, p = {p}. İlişkinin gücü {etki_yorumu} düzeydedir "
        "(Cramér's V = {v})."
    ),
    "cronbachs_alpha": (
        "Ölçeğin {madde_sayısı} maddeden oluşan formunun iç tutarlılık güvenirlik "
        "katsayısı Cronbach α = {alfa} olarak hesaplanmıştır (n = {n}). Bu değer, "
        "ölçeğin güvenirliğinin {güvenirlik_yorumu} düzeyde olduğunu göstermektedir."
    ),
}


def render_from_template(payload: dict[str, Any]) -> str:
    """Deterministic Turkish interpretation — the §3.6 fallback path."""
    renderer = RENDERERS.get(payload["analysis_type"])
    if renderer is None:  # pragma: no cover — renderers track the registry
        raise KeyError(f"No interpretation template for {payload['analysis_type']!r}")
    return renderer(payload)
