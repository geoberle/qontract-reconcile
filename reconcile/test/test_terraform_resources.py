import reconcile.terraform_resources as integ

import pytest


def test_filter_no_managed_tf_resources():
    ra = {'account': 'a', 'provider': 'p', 'identifier': 'i' }
    ns1 = {'name': 'n1', 'managedTerraformResources': False, 'terraformResources': [], 'cluster': {'name': 'cl1'}}
    ns2 = {'name': 'n2', 'managedTerraformResources': True, 'terraformResources': [ra], 'cluster': {'name': 'cl2'}}
    namespaces = [ns1, ns2]
    filtered, _ = integ.detect_tf_resources(namespaces, None)
    assert filtered == [ns2]


def test_filter_tf_namespaces_with_account_name():
    ra = {'account': 'a', 'provider': 'p', 'identifier': 'i1'}
    rb = {'account': 'b', 'provider': 'p', 'identifier': 'i2'}
    ns1 = {'name': 'n1', 'managedTerraformResources': True, 'terraformResources': [ra], 'cluster': {'name': 'cl1'}}
    ns2 = {'name': 'n2', 'managedTerraformResources': True, 'terraformResources': [rb], 'cluster': {'name': 'cl2'}}
    namespaces = [ns1, ns2]
    filtered, _ = integ.detect_tf_resources(namespaces, 'a')
    assert filtered == [ns1]


def test_filter_tf_namespaces_without_account_name():
    ra = {'account': 'a', 'provider': 'p', 'identifier': 'i1'}
    rb = {'account': 'b', 'provider': 'p', 'identifier': 'i2'}
    ns1 = {'name': 'n1', 'managedTerraformResources': True, 'terraformResources': [ra], 'cluster': {'name': 'cl1'}}
    ns2 = {'name': 'n2', 'managedTerraformResources': True, 'terraformResources': [rb], 'cluster': {'name': 'cl2'}}
    namespaces = [ns1, ns2]
    filtered, _ = integ.detect_tf_resources(namespaces, None)
    assert filtered == namespaces
