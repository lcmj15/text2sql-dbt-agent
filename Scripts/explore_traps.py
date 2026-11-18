import duckdb

con = duckdb.connect("warehouse/fitloop.duckdb", read_only=True)

queries = {
    "1. Todas as linhas (signup + trial + pago)":
        "select count(*) from gold.fct_conversions",
    "2. So pagos, mas incluindo campanhas de QA":
        "select count(*) from gold.fct_conversions where conversion_type = 'paid_subscription'",
    "3. Pagos, sem QA, mas com INNER JOIN (perde o organico)":
        """select count(*) from gold.fct_conversions f
           join gold.dim_campaigns c using (campaign_id)
           where f.conversion_type = 'paid_subscription' and not c.is_internal""",
    "4. CORRETO: pagos, sem QA, com organico (LEFT JOIN)":
        """select count(*) from gold.fct_conversions f
           left join gold.dim_campaigns c using (campaign_id)
           where f.conversion_type = 'paid_subscription'
             and coalesce(c.is_internal, false) = false""",
}

print('Pergunta: "Quantas conversoes tivemos em 2025?"\n')
for label, sql in queries.items():
    print(f"{con.execute(sql).fetchone()[0]:>7,}  {label}")