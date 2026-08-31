"""Validação simples para bloquear instruções SQL que não sejam apenas de
leitura, usada nos Custom Checks — que correm SQL escrito livremente pelo
utilizador contra a base de dados de negócio.

Isto é uma proteção adicional (defesa em profundidade), não substitui a
recomendação do README de usares sempre um login SQL só de leitura: uma
function ou view chamada pela query pode teoricamente esconder um efeito
secundário que este scanner de texto não consegue detetar. Mesmo assim,
bloqueia por completo o caso mais comum de erro/acidente: escrever sem
querer um UPDATE/DELETE/DROP no sítio errado.
"""
import re

_FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "MERGE",
    "EXEC", "EXECUTE", "CREATE", "GRANT", "REVOKE", "DENY", "BACKUP",
    "RESTORE", "SHUTDOWN", "KILL", "DBCC", "INTO", "OPENROWSET",
    "OPENDATASOURCE", "BULK",
]
_FORBIDDEN_KEYWORD_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)
_SP_XP_RE = re.compile(r"\b(sp|xp)_\w*", re.IGNORECASE)
_STARTS_OK_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _strip_strings_and_comments(sql: str) -> str:
    """Substitui literais de texto ('...') e comentários (--, /* */) por
    espaços, para a validação abaixo não ser enganada por palavras-chave
    escondidas dentro de strings/comentários (ex: um filtro de texto que
    contenha literalmente a palavra "update")."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            i = j
            out.append(" ")
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def validate_select_only(sql_text: str) -> None:
    """Levanta ValueError com uma mensagem explicativa se a query não for
    apenas de leitura. Aceita SELECT (com UNION/JOIN/subqueries/agregações)
    e CTEs via WITH; bloqueia tudo o que altere dados ou esquema, execute
    procedimentos, ou empilhe várias instruções na mesma query."""
    if not sql_text or not sql_text.strip():
        raise ValueError("A query não pode estar vazia.")

    cleaned = _strip_strings_and_comments(sql_text)

    if not _STARTS_OK_RE.match(cleaned):
        raise ValueError(
            "Só são permitidas queries de leitura: tem de começar por SELECT "
            "(ou WITH, se usares CTEs)."
        )

    match = _FORBIDDEN_KEYWORD_RE.search(cleaned)
    if match:
        raise ValueError(
            f"A palavra-chave '{match.group(1).upper()}' não é permitida nos "
            "Custom Checks — só são aceites queries de leitura (SELECT)."
        )

    if _SP_XP_RE.search(cleaned):
        raise ValueError(
            "Não é permitido chamar procedimentos armazenados (nomes que "
            "comecem por 'sp_' ou 'xp_') nos Custom Checks."
        )

    without_trailing = cleaned.strip()
    if without_trailing.endswith(";"):
        without_trailing = without_trailing[:-1]
    if ";" in without_trailing:
        raise ValueError(
            "Não são permitidas várias instruções separadas por ';' — usa "
            "apenas uma única query SELECT."
        )
