using System.Diagnostics;
using System.Text;

namespace MirrorDisplay;

static class CoinRead
{
    static Process? process;
    static readonly object gate = new();

    public static (string Coin, string Result) Ask(string imagePath)
    {
        string? script = ScriptPath();
        if (script == null)
        {
            return ("", "");
        }

        lock (gate)
        {
            if (!Ensure(script))
            {
                return ("", "");
            }

            try
            {
                process!.StandardInput.WriteLine(imagePath);
                process.StandardInput.Flush();
                var read = Task.Run(() => process.StandardOutput.ReadLine());
                if (!read.Wait(60000) || read.Result == null)
                {
                    Stop();
                    return ("", "");
                }

                string[] parts = read.Result.Split('\t');
                string coin = parts.Length > 0 ? parts[0].Trim() : "";
                string result = parts.Length > 1 ? parts[1].Trim() : "";
                return (coin, result);
            }
            catch
            {
                Stop();
                return ("", "");
            }
        }
    }

    static bool Ensure(string script)
    {
        if (process is { HasExited: false })
        {
            return true;
        }

        Stop();
        var start = new ProcessStartInfo
        {
            FileName = "python",
            Arguments = "-u \"" + script + "\"",
            WorkingDirectory = Path.GetDirectoryName(script)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardInputEncoding = Encoding.UTF8,
        };
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        start.Environment["PYTHONUNBUFFERED"] = "1";
        try
        {
            process = Process.Start(start);
            if (process == null || process.HasExited)
            {
                process = null;
                return false;
            }

            var ready = Task.Run(() => process.StandardOutput.ReadLine());
            if (!ready.Wait(60000) || ready.Result != "ready")
            {
                Stop();
                return false;
            }
        }
        catch
        {
            Stop();
            return false;
        }

        return true;
    }

    static void Stop()
    {
        if (process == null)
        {
            return;
        }

        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            /* 次の読みで起動し直す */
        }

        process.Dispose();
        process = null;
    }

    static string? ScriptPath()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            string script = Path.Combine(dir.FullName, "iphone_mirror", "windows", "MirrorDisplay", "coin_read.py");
            string model = Path.Combine(dir.FullName, "tsumtsum-screen-recognition", "data", "models", "coin.pt");
            if (File.Exists(script) && File.Exists(model))
            {
                return script;
            }

            dir = dir.Parent;
        }

        return null;
    }
}
