import yaml

with open('grafana/provisioning/alerting/alerts.yml', 'r') as f:
    data = yaml.safe_load(f)

for group in data.get('groups', []):
    for rule in group.get('rules', []):
        if 'data' in rule:
            for item in rule['data']:
                if item.get('datasourceUid') == 'prometheus':
                    if 'model' in item:
                        item['model']['instant'] = True

with open('grafana/provisioning/alerting/alerts.yml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
