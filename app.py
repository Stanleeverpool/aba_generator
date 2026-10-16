import os
import re
from itertools import product
from flask import Flask, request, render_template_string

app = Flask(__name__)

# ==========================================
# 1. PARSER
# ==========================================
def parse_aba_input(text):
    data = {
        "literals": set(),
        "assumptions": set(),
        "contraries": {},
        "rules": [],
        "preferences": {}
    }

    lines = text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            lower_l = line.lower()
            if "literal" in lower_l:
                current_section = "literals"
            elif "assumption" in lower_l:
                current_section = "assumptions"
            elif "contrar" in lower_l:
                current_section = "contraries"
            elif "rule" in lower_l:
                current_section = "rules"
            elif "preference" in lower_l:
                current_section = "preferences"
            continue

        if current_section == "literals":
            m = re.search(r"L:\s*\[(.*?)\]", line)
            if m:
                items = [x.strip() for x in m.group(1).split(",") if x.strip()]
                data["literals"].update(items)

        elif current_section == "assumptions":
            m = re.search(r"A:\s*\[(.*?)\]", line)
            if m:
                items = [x.strip() for x in m.group(1).split(",") if x.strip()]
                data["assumptions"].update(items)

        elif current_section == "contraries":
            m = re.search(r"C\((\w+)\):\s*(\w+)", line)
            if m:
                data["contraries"][m.group(1)] = m.group(2)

        elif current_section == "rules":
            m = re.search(r"\[(.*?)\]:\s*(\w+)\s*<-(.*)", line)
            if m:
                r_id = m.group(1).strip()
                head = m.group(2).strip()
                body_str = m.group(3).strip()
                body = [x.strip() for x in body_str.split(",") if x.strip()] if body_str else []
                data["rules"].append((r_id, head, body))

        elif current_section == "preferences":
            m = re.search(r"PREF:\s*(.*)", line)
            if m:
                pref_expr = m.group(1).strip()
                levels = pref_expr.split(">")
                rank = len(levels)
                for lvl in levels:
                    vars_in_lvl = [v.strip() for v in lvl.split(",") if v.strip()]
                    for v in vars_in_lvl:
                        data["preferences"][v] = rank
                    rank -= 1

    return data

# ==========================================
# 2. CONVERSION & NORMALISATION
# ==========================================
def make_atomic_and_non_circular(aba):
    cleaned_rules = []
    for r_id, head, body in aba["rules"]:
        # Élimination des boucles réflexives directes
        if head in body:
            continue
        cleaned_rules.append((r_id, head, body))
    aba["rules"] = cleaned_rules
    return aba

# ==========================================
# 3. GÉNÉRATION DES ARGUMENTS
# ==========================================
def find_arguments(aba):
    assumptions = aba["assumptions"]
    rules = aba["rules"]

    derivations = {lit: set() for lit in aba["literals"]}

    for a in assumptions:
        derivations[a].add((frozenset([a]), frozenset()))

    changed = True
    iterations = 0
    max_iter = 30

    while changed and iterations < max_iter:
        changed = False
        iterations += 1
        for r_id, head, body in rules:
            if not body:
                entry = (frozenset(), frozenset([r_id]))
                if entry not in derivations[head]:
                    derivations[head].add(entry)
                    changed = True
            else:
                combos = [derivations[p] for p in body]
                if all(len(c) > 0 for c in combos):
                    for combo in product(*combos):
                        comb_assumptions = frozenset().union(*[c[0] for c in combo])
                        comb_rules = frozenset([r_id]).union(*[c[1] for c in combo])
                        entry = (comb_assumptions, comb_rules)
                        if entry not in derivations[head]:
                            derivations[head].add(entry)
                            changed = True

    arguments = []
    idx = 1
    for lit in sorted(derivations.keys()):
        for supp, r_used in derivations[lit]:
            arguments.append({
                "id": f"Arg_{idx}",
                "claim": lit,
                "support": sorted(list(supp)),
                "rules": sorted(list(r_used))
            })
            idx += 1

    return arguments

# ==========================================
# 4. GESTION DES PRÉFÉRENCES & ATTAQUES
# ==========================================
def compare_preferences(supp1, supp2, prefs):
    def score(supp):
        if not supp:
            return float("inf")
        return min(prefs.get(a, 0) for a in supp)

    return score(supp1) >= score(supp2)

def compute_attacks(arguments, contraries, prefs, attack_type="normal"):
    attacks = []
    for a1 in arguments:
        for a2 in arguments:
            for assumption in a2["support"]:
                if contraries.get(assumption) == a1["claim"]:
                    pref_a1_ge_a2 = compare_preferences(a1["support"], a2["support"], prefs)
                    pref_a2_ge_a1 = compare_preferences(a2["support"], a1["support"], prefs)

                    if attack_type == "normal":
                        if pref_a1_ge_a2:
                            attacks.append((a1["id"], a2["id"]))
                    elif attack_type == "reverse":
                        if pref_a2_ge_a1:
                            attacks.append((a2["id"], a1["id"]))
                    else:
                        attacks.append((a1["id"], a2["id"]))
                    break
    return sorted(list(set(attacks)))

# ==========================================
# 5. TEMPLATE HTML
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>ABA Generator</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 30px auto; max-width: 950px; line-height: 1.5; color: #333; }
        h1 { margin-bottom: 5px; }
        textarea { width: 100%; height: 260px; font-family: monospace; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        .controls { margin-top: 15px; margin-bottom: 25px; display: flex; align-items: center; gap: 20px; }
        button { background-color: #0066cc; color: white; border: none; padding: 10px 20px; font-size: 15px; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0052a3; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background-color: #f7f7f7; }
        .attack-box { background: #fafafa; border: 1px solid #e0e0e0; border-radius: 4px; padding: 12px; margin-top: 10px; }
        .badge { display: inline-block; background: #eef2ff; color: #3730a3; padding: 3px 8px; border-radius: 4px; margin: 3px; font-family: monospace; }
    </style>
</head>
<body>
    <h1>Assumption-Based Argumentation (ABA) Generator</h1>
    <p>Saisis la spécification ABA au format requis pour calculer les arguments et les attaques.</p>

    <form method="POST">
        <textarea name="aba_input">{{ raw_input }}</textarea>
        <div class="controls">
            <label><strong>Mode d'attaque :</strong></label>
            <label><input type="radio" name="attack_type" value="normal" {% if attack_type == 'normal' %}checked{% endif %}> Normale</label>
            <label><input type="radio" name="attack_type" value="reverse" {% if attack_type == 'reverse' %}checked{% endif %}> Inverse (Reverse)</label>
            <label><input type="radio" name="attack_type" value="none" {% if attack_type == 'none' %}checked{% endif %}> Sans préférences</label>
            <button type="submit">Calculer</button>
        </div>
    </form>

    {% if evaluated %}
        <hr>
        <h2>Résultats</h2>
        <h3>1. Arguments générés ({{ arguments|length }})</h3>
        {% if arguments %}
            <table>
                <thead>
                    <tr>
                        <th>Identifiant</th>
                        <th>Conclusion (Claim)</th>
                        <th>Support (Hypothèses)</th>
                        <th>Règles appliquées</th>
                    </tr>
                </thead>
                <tbody>
                    {% for arg in arguments %}
                        <tr>
                            <td><strong>{{ arg.id }}</strong></td>
                            <td>{{ arg.claim }}</td>
                            <td>{% if arg.support %}{ {{ arg.support|join(', ') }} }{% else %}∅{% endif %}</td>
                            <td>{% if arg.rules %}{ {{ arg.rules|join(', ') }} }{% else %}∅{% endif %}</td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>Aucun argument déductible.</p>
        {% endif %}

        <h3>2. Attaques ({{ attacks|length }})</h3>
        <div class="attack-box">
            {% if attacks %}
                {% for u, v in attacks %}
                    <span class="badge">{{ u }} &rarr; {{ v }}</span>
                {% endfor %}
            {% else %}
                <p style="margin: 0;">Aucune relation d'attaque détectée.</p>
            {% endif %}
        </div>
    {% endif %}
</body>
</html>
"""

DEFAULT_INPUT = """## Literals
L: [a,b,c,q,p,r,s,t]

## Assumptions
A: [a,b,c]

## Contraries
C(a): r
C(b): s
C(c): t

## Rules
[r1]: p <- q,a
[r2]: q <-
[r3]: r <- b,c
[r4]: t <- p,c
[r5]: s <- t

## Preferences
PREF: a > b"""

@app.route("/", methods=["GET", "POST"])
def index():
    raw_input = DEFAULT_INPUT
    attack_type = "normal"
    arguments = []
    attacks = []
    evaluated = False

    if request.method == "POST":
        raw_input = request.form.get("aba_input", "")
        attack_type = request.form.get("attack_type", "normal")
        aba = parse_aba_input(raw_input)
        aba = make_atomic_and_non_circular(aba)
        arguments = find_arguments(aba)
        attacks = compute_attacks(arguments, aba["contraries"], aba["preferences"], attack_type)
        evaluated = True

    return render_template_string(
        HTML_TEMPLATE,
        raw_input=raw_input,
        attack_type=attack_type,
        arguments=arguments,
        attacks=attacks,
        evaluated=evaluated
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)