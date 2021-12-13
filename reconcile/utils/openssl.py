from OpenSSL import crypto
import datetime


def certificate_matches_host(certificate, host):
    common_name = get_certificate_common_name(certificate)
    return host.endswith(common_name.replace('*.', ''))


def get_certificate_common_name(certificate):
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, certificate)
    subject = cert.get_subject()
    return subject.CN


def get_certificate_expiration(certificate):
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, certificate)
    return datetime.datetime.strptime(cert.get_notAfter().decode('utf-8'), '%Y%m%d%H%M%SZ')
