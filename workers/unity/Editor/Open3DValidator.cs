using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class Open3DValidator
{
    [Serializable]
    private class Check
    {
        public string check_id;
        public string status;
        public string message;
    }

    [Serializable]
    private class Report
    {
        public string schema_version = "0.1.0";
        public string status;
        public string input;
        public int objects;
        public int meshes;
        public int materials;
        public Check[] checks;
    }

    public static void Run()
    {
        string input = Argument("-open3dInput");
        string output = Argument("-open3dOutput");
        Report report = new Report { input = input };
        try
        {
            if (String.IsNullOrEmpty(input) || String.IsNullOrEmpty(output))
                throw new InvalidOperationException("-open3dInput and -open3dOutput are required");

            AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
            AssetImporter importer = AssetImporter.GetAtPath(input);
            if (importer == null)
                throw new InvalidOperationException("Unity did not create an importer for " + input);

            UnityEngine.Object[] imported = AssetDatabase.LoadAllAssetsAtPath(input);
            int meshCount = 0;
            int materialCount = 0;
            int objectCount = 0;
            foreach (UnityEngine.Object item in imported)
            {
                if (item is Mesh) meshCount++;
                if (item is Material) materialCount++;
                if (item is GameObject) objectCount++;
            }

            bool importerPolicyPass = true;
            if (importer is ModelImporter model)
                importerPolicyPass = model.globalScale > 0f && model.importNormals != ModelImporterNormals.None;

            report.objects = objectCount;
            report.meshes = meshCount;
            report.materials = materialCount;
            report.status = importerPolicyPass && (meshCount > 0 || objectCount > 0) ? "PASS" : "FAIL";
            report.checks = new[]
            {
                new Check { check_id = "unity.importer_present", status = "PASS", message = importer.GetType().Name },
                new Check { check_id = "unity.mesh_or_object", status = meshCount > 0 || objectCount > 0 ? "PASS" : "FAIL", message = objectCount + " objects, " + meshCount + " meshes" },
                new Check { check_id = "unity.import_policy", status = importerPolicyPass ? "PASS" : "FAIL", message = "positive scale and normals enabled" },
                new Check { check_id = "unity.materials", status = materialCount > 0 ? "PASS" : "WARN", message = materialCount + " materials" },
            };
            File.WriteAllText(output, JsonUtility.ToJson(report, true));
            EditorApplication.Exit(report.status == "PASS" ? 0 : 1);
        }
        catch (Exception error)
        {
            report.status = "FAIL";
            report.checks = new[] { new Check { check_id = "unity.validator", status = "FAIL", message = error.Message } };
            if (!String.IsNullOrEmpty(output))
                File.WriteAllText(output, JsonUtility.ToJson(report, true));
            EditorApplication.Exit(1);
        }
    }

    private static string Argument(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i + 1 < args.Length; i++)
            if (args[i] == name) return args[i + 1];
        return String.Empty;
    }
}
