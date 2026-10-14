import yaml

with open('/home/tiago2609/monitoring/grafana/provisioning/alerting/alerts.yml', 'r') as f:
    data = yaml.safe_load(f)

for group in data.get('groups', []):
    for rule in group.get('rules', []):
        if 'data' in rule:
            # Get the expression from the original PromQL query
            a_data = rule['data'][0]
            if a_data.get('datasourceUid') == 'prometheus':
                prom_expr = a_data['model']['expr']
                
                # Rebuild data pipeline: A (query), B (reduce), C (math)
                rule['condition'] = 'C'
                rule['data'] = [
                    {
                        'refId': 'A',
                        'datasourceUid': 'prometheus',
                        'relativeTimeRange': {'from': 300, 'to': 0},
                        'model': {
                            'expr': prom_expr,
                            'refId': 'A'
                        }
                    },
                    {
                        'refId': 'B',
                        'datasourceUid': '__expr__',
                        'model': {
                            'refId': 'B',
                            'type': 'reduce',
                            'datasource': {'type': '__expr__', 'uid': '__expr__'},
                            'expression': 'A',
                            'reducer': 'last',
                            'conditions': [{'evaluator': {'params': [0], 'type': 'gt'}, 'operator': {'type': 'and'}, 'query': {'params': ['A']}, 'reducer': {'params': [], 'type': 'last'}, 'type': 'query'}]
                        }
                    },
                    {
                        'refId': 'C',
                        'datasourceUid': '__expr__',
                        'model': {
                            'refId': 'C',
                            'type': 'math',
                            'datasource': {'type': '__expr__', 'uid': '__expr__'},
                            'expression': '$B > 0',
                            'conditions': [{'evaluator': {'params': [0], 'type': 'gt'}, 'operator': {'type': 'and'}, 'query': {'params': ['C']}, 'reducer': {'params': [], 'type': 'last'}, 'type': 'query'}]
                        }
                    }
                ]

with open('/home/tiago2609/monitoring/grafana/provisioning/alerting/alerts.yml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

