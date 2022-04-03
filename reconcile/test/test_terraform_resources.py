from unittest import TestCase
import reconcile.terraform_resources as integ


class TestSupportFunctions(TestCase):
    def test_filter_no_managed_tf_resources(self):
        ra = {"account": "a", "identifier": "a", "provider": "p"}
        ns1 = {
            "name": "ns1",
            "managedTerraformResources": False,
            "terraformResources": [],
            "cluster": {"name": "c"},
        }
        ns2 = {
            "name": "ns2",
            "managedTerraformResources": True,
            "terraformResources": [ra],
            "cluster": {"name": "c"},
        }
        namespaces = [ns1, ns2]
        filtered, _ = integ.init_tf_resource_specs(namespaces, None)
        self.assertEqual(filtered, [ns2])

    def test_filter_tf_namespaces_with_account_name(self):
        ra = {"account": "a", "identifier": "a", "provider": "p"}
        rb = {"account": "b", "identifier": "b", "provider": "p"}
        ns1 = {
            "name": "ns1",
            "managedTerraformResources": True,
            "terraformResources": [ra],
            "cluster": {"name": "c"},
        }
        ns2 = {
            "name": "ns2",
            "managedTerraformResources": True,
            "terraformResources": [rb],
            "cluster": {"name": "c"},
        }
        namespaces = [ns1, ns2]
        filtered, _ = integ.init_tf_resource_specs(namespaces, "a")
        self.assertEqual(filtered, [ns1])

    def test_filter_tf_namespaces_without_account_name(self):
        ra = {"account": "a", "identifier": "a", "provider": "p"}
        rb = {"account": "b", "identifier": "b", "provider": "p"}
        ns1 = {
            "name": "ns1",
            "managedTerraformResources": True,
            "terraformResources": [ra],
            "cluster": {"name": "c"},
        }
        ns2 = {
            "name": "ns2",
            "managedTerraformResources": True,
            "terraformResources": [rb],
            "cluster": {"name": "c"},
        }
        namespaces = [ns1, ns2]
        filtered, _ = integ.init_tf_resource_specs(namespaces, None)
        self.assertEqual(filtered, namespaces)

    def test_filter_no_tf_resources_no_account_filter(self):
        """
        this test makes sure that a namespace is returned even if it has no resources
        attached. this way we can delete the last terraform resources that might have been
        defined on the namespace previously
        """
        ra = {"account": "a", "identifier": "a", "provider": "p"}
        ns1 = {
            "name": "ns1",
            "managedTerraformResources": True,
            "terraformResources": [],
            "cluster": {"name": "c"},
        }
        ns2 = {
            "name": "ns2",
            "managedTerraformResources": True,
            "terraformResources": [ra],
            "cluster": {"name": "c"},
        }

        namespaces = [ns1, ns2]
        filtered, _ = integ.init_tf_resource_specs(namespaces, None)
        self.assertEqual(filtered, [ns1, ns2])

    def test_filter_no_tf_resources_with_account_filter(self):
        """
        even if an account filter is defined, a namespace without resources is returned
        to enable terraform resource deletion. in contrast to that a namespace with a resource
        that does not match the account will not be returned.

        the implication of this behaviour is that a namespace with managedTerraformResources=true but
        no resources is processed in each terraform-resources shard. this is not really a problem, since
        the resources of a namespace are still filtered later in the reconciling code if an account
        is given.
        """
        ra = {"account": "a", "identifier": "a", "provider": "p"}
        ns1 = {
            "name": "ns1",
            "managedTerraformResources": True,
            "terraformResources": [],
            "cluster": {"name": "c"},
        }
        ns2 = {
            "name": "ns2",
            "managedTerraformResources": True,
            "terraformResources": [ra],
            "cluster": {"name": "c"},
        }
        namespaces = [ns1, ns2]
        filtered, _ = integ.init_tf_resource_specs(namespaces, "b")
        self.assertEqual(filtered, [ns1])
