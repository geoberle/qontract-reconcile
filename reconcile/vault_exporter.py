from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient, SecretAccessForbidden
from reconcile.utils import gql
from reconcile.utils import config
from reconcile.utils import openssl
from reconcile.queries import get_vault_queries
import datetime
import base64


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

NOW = datetime.datetime.now()
SEVEN_DAYS = NOW + datetime.timedelta(days=10)
THIRTY_DAYS = NOW + datetime.timedelta(days=30)
config.init_from_toml("config.ci-int.toml")
gql.init_from_config(integration=QONTRACT_INTEGRATION)
client = VaultClient()

def get_cert_from_value(value: str):
    if value:
        if "-----BEGIN CERTIFICATE-----" in value:
            return value, "pem"

        if len(value) > 100:
            try:
                decoded = base64.decodestring(value)
                if "-----BEGIN CERTIFICATE-----" in decoded:
                    return decoded, "encpem"
            except:
                pass

    return None, None

def check_fields(path, fields):
    if fields:
        for key, value in fields.items():
            cert_value, cert_type = get_cert_from_value(value)
            if cert_value != None:
                expiration_date = openssl.get_certificate_expiration(value)
                if expiration_date < NOW:
                    print(f"cert {path}:{key} ({cert_type}) expired at {expiration_date}")
                elif expiration_date < SEVEN_DAYS:
                    print(f"cert {path}:{key} ({cert_type}) will expired in < 7 days at {expiration_date}")
                elif expiration_date < THIRTY_DAYS:
                    print(f"cert {path}:{key} ({cert_type}) will expired in < 30 days at {expiration_date}")
                else:
                    print(f"cert {path}:{key} ({cert_type}) is still valid {expiration_date}")

def check_secret(secret):
    try:
        check_fields(secret.get("path"), client.read_all(secret))
    except SecretAccessForbidden as e:
        pass

for ns in get_vault_queries():
    if ns.get("openshiftResources"):
        for res in ns.get("openshiftResources"):
            if res["provider"] == "vault-secret":
                check_secret(res)
    if ns.get("sharedResources"):
        for sr in ns.get("sharedResources"):
            if sr.get("openshiftResources"):
                for res in sr.get("openshiftResources"):
                    if res["provider"] == "vault-secret":
                        check_secret(res)
