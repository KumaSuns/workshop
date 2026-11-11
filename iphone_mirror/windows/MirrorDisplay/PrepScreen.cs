using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Text.Json;

namespace MirrorDisplay;

static class PrepScreen
{
    const int IconCount = 7;
    const double Seen = 0.28;

    static readonly (string Key, double X, double Y, double W, double H)[] Fallback =
    {
        ("score_plus", 135.0 / 1320, 1232.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("coin_plus", 412.0 / 1320, 1236.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("exp_plus", 679.0 / 1320, 1237.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("time_plus", 942.0 / 1320, 1240.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("bomb_plus", 131.0 / 1320, 1571.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("5to4", 402.0 / 1320, 1576.0 / 2868, 239.0 / 1320, 247.0 / 2868),
        ("combo_plus", 679.0 / 1320, 1571.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    };

    static (double X, double Y, double W, double H)[] slots = Fallback.Select(item => (item.X, item.Y, item.W, item.H)).ToArray();
    static volatile FaceBook book = FaceBook.Empty;

    public static string? IconsDirectory { get; private set; }

    public readonly record struct ReadResult(string Tsum, bool[] On, bool Screen);

    public static void Start()
    {
        string? workshop = WorkshopRoot();
        if (string.IsNullOrEmpty(workshop))
        {
            return;
        }

        IconsDirectory = Path.Combine(workshop, "video-frame-extractor", "app", "assets", "icons");

        string slotsPath = Path.Combine(workshop, "tsumtsum-screen-recognition", "data", "item_slots.json");
        slots = LoadSlots(slotsPath);
        string images = Path.Combine(workshop, "video-frame-extractor", "app", "assets", "images", "use_tsums");
        string registry = Path.Combine(workshop, "video-frame-extractor", "app", "assets", "models", "use_tsum", "registry.json");
        Task.Run(() =>
        {
            try
            {
                book = FaceBook.Load(images, registry);
            }
            catch
            {
                book = FaceBook.Empty;
            }
        });
    }

    public static ReadResult Read(Bitmap image)
    {
        var off = new bool[IconCount];
        if (image.Width < 8 || image.Height <= image.Width)
        {
            return new ReadResult("", off, false);
        }

        var pixels = Pixels.From(image);
        int seen = 0;
        for (int i = 0; i < slots.Length && i < IconCount; i++)
        {
            var (yellow, blue) = SlotColor(pixels, slots[i]);
            if (yellow + blue < Seen)
            {
                continue;
            }

            seen++;
            off[i] = yellow > blue;
        }

        if (seen < 5)
        {
            return new ReadResult("", new bool[IconCount], false);
        }

        string name = "";
        try
        {
            name = book.Match(pixels);
        }
        catch
        {
            name = "";
        }

        return new ReadResult(name, off, true);
    }

    static (double Yellow, double Blue) SlotColor(Pixels pixels, (double X, double Y, double W, double H) slot)
    {
        int x = (int)Math.Round(slot.X * pixels.Width);
        int y = (int)Math.Round(slot.Y * pixels.Height);
        int w = Math.Max(1, (int)Math.Round(slot.W * pixels.Width));
        int h = Math.Max(1, (int)Math.Round(slot.H * pixels.Height));
        x = Math.Clamp(x, 0, pixels.Width - 1);
        y = Math.Clamp(y, 0, pixels.Height - 1);
        w = Math.Min(w, pixels.Width - x);
        h = Math.Min(h, pixels.Height - y);
        int insetX = Math.Max(1, (int)(w * 0.2));
        int insetY = Math.Max(1, (int)(h * 0.2));
        int left = x + insetX;
        int top = y + insetY;
        int right = x + w - insetX;
        int bottom = y + h - insetY;
        if (right <= left || bottom <= top)
        {
            return (0, 0);
        }

        int stepX = Math.Max(1, (right - left) / 24);
        int stepY = Math.Max(1, (bottom - top) / 24);
        int total = 0;
        int yellow = 0;
        int blue = 0;
        for (int yy = top; yy < bottom; yy += stepY)
        {
            for (int xx = left; xx < right; xx += stepX)
            {
                pixels.Read(xx, yy, out int r, out int g, out int b);
                RgbToHsv(r, g, b, out double hue, out double sat, out double val);
                total++;
                if (hue is >= 0.10 and <= 0.18 && sat >= 0.30 && val >= 0.35)
                {
                    yellow++;
                }
                else if (hue is >= 0.52 and <= 0.72 && sat >= 0.28 && val >= 0.25)
                {
                    blue++;
                }
            }
        }

        if (total == 0)
        {
            return (0, 0);
        }

        return (yellow / (double)total, blue / (double)total);
    }

    static (double X, double Y, double W, double H)[] LoadSlots(string path)
    {
        var loaded = Fallback.Select(item => (item.X, item.Y, item.W, item.H)).ToArray();
        if (!File.Exists(path))
        {
            return loaded;
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            for (int i = 0; i < Fallback.Length; i++)
            {
                if (!doc.RootElement.TryGetProperty(Fallback[i].Key, out var list) || list.GetArrayLength() == 0)
                {
                    continue;
                }

                var item = list[0];
                var box = item.GetProperty("box");
                double sw = item.GetProperty("width").GetDouble();
                double sh = item.GetProperty("height").GetDouble();
                if (sw < 1 || sh < 1)
                {
                    continue;
                }

                loaded[i] = (
                    box.GetProperty("x").GetDouble() / sw,
                    box.GetProperty("y").GetDouble() / sh,
                    box.GetProperty("w").GetDouble() / sw,
                    box.GetProperty("h").GetDouble() / sh);
            }
        }
        catch
        {
            return Fallback.Select(item => (item.X, item.Y, item.W, item.H)).ToArray();
        }

        return loaded;
    }

    static string? WorkshopRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            string slotsPath = Path.Combine(dir.FullName, "tsumtsum-screen-recognition", "data", "item_slots.json");
            string images = Path.Combine(dir.FullName, "video-frame-extractor", "app", "assets", "images", "use_tsums");
            if (File.Exists(slotsPath) && Directory.Exists(images))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        return null;
    }

    static void RgbToHsv(int r, int g, int b, out double hue, out double sat, out double val)
    {
        double rf = r / 255.0;
        double gf = g / 255.0;
        double bf = b / 255.0;
        double max = Math.Max(rf, Math.Max(gf, bf));
        double min = Math.Min(rf, Math.Min(gf, bf));
        val = max;
        double delta = max - min;
        if (delta == 0 || max == 0)
        {
            hue = 0;
            sat = 0;
            return;
        }

        sat = delta / max;
        double rc = (max - rf) / delta;
        double gc = (max - gf) / delta;
        double bc = (max - bf) / delta;
        double h = rf == max ? bc - gc : gf == max ? 2.0 + rc - bc : 4.0 + gc - rc;
        hue = (h / 6.0) % 1.0;
        if (hue < 0)
        {
            hue += 1;
        }
    }

    sealed class FaceBook
    {
        public static readonly FaceBook Empty = new(Array.Empty<Face>());
        readonly Face[] faces;

        FaceBook(Face[] faces)
        {
            this.faces = faces;
        }

        public static FaceBook Load(string imagesRoot, string registryPath)
        {
            if (!Directory.Exists(imagesRoot))
            {
                return Empty;
            }

            var names = ReadNames(registryPath);
            var files = Directory.EnumerateDirectories(imagesRoot)
                .SelectMany(dir => Directory.EnumerateFiles(dir)
                    .Where(path => IsImage(path))
                    .Select(path => (Id: Path.GetFileName(dir) ?? "", Path: path)))
                .ToArray();
            string signature = Signature(files.Select(file => file.Path));
            string cache = Path.Combine(Path.GetTempPath(), "mirror-use-tsum-faces.bin");
            var cached = TryReadCache(cache, signature, names);
            if (cached != null)
            {
                return cached;
            }

            var built = new List<Face>();
            foreach (var (id, path) in files)
            {
                try
                {
                    using var image = new Bitmap(path);
                    using var face = CropFace(image);
                    if (face == null)
                    {
                        continue;
                    }

                    built.Add(new Face(id, names.GetValueOrDefault(id, id), Feature(face)));
                }
                catch
                {
                    /* この見本は飛ばす */
                }
            }

            var book = new FaceBook(built.ToArray());
            TryWriteCache(cache, signature, book.faces);
            return book;
        }

        public string Match(Pixels pixels)
        {
            if (faces.Length == 0)
            {
                return "";
            }

            using var face = CropFace(pixels);
            if (face == null)
            {
                return "";
            }

            float[] feature = Feature(face);
            var best = new Dictionary<string, (double Dist, string Name)>();
            foreach (var sample in faces)
            {
                double dist = L1(feature, sample.Values);
                if (!best.TryGetValue(sample.Id, out var held) || dist < held.Dist)
                {
                    best[sample.Id] = (dist, sample.Name);
                }
            }

            string name = "";
            double first = double.PositiveInfinity;
            double second = double.PositiveInfinity;
            foreach (var item in best.Values)
            {
                if (item.Dist < first)
                {
                    second = first;
                    first = item.Dist;
                    name = item.Name;
                }
                else if (item.Dist < second)
                {
                    second = item.Dist;
                }
            }

            if (double.IsPositiveInfinity(first) || first >= 0.08 || first * 2 >= second)
            {
                return "";
            }

            return name;
        }

        static Dictionary<string, string> ReadNames(string path)
        {
            var names = new Dictionary<string, string>();
            if (!File.Exists(path))
            {
                return names;
            }

            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(path));
                foreach (var prop in doc.RootElement.EnumerateObject())
                {
                    names[prop.Name] = prop.Value.GetString() ?? prop.Name;
                }
            }
            catch
            {
                return names;
            }

            return names;
        }

        static string Signature(IEnumerable<string> paths)
        {
            long count = 0;
            long bytes = 0;
            long ticks = 0;
            foreach (string path in paths)
            {
                var info = new FileInfo(path);
                count++;
                bytes += info.Length;
                ticks = Math.Max(ticks, info.LastWriteTimeUtc.Ticks);
            }

            return count + ":" + bytes + ":" + ticks;
        }

        static bool IsImage(string path)
        {
            string ext = Path.GetExtension(path);
            return ext.Equals(".png", StringComparison.OrdinalIgnoreCase)
                || ext.Equals(".jpg", StringComparison.OrdinalIgnoreCase)
                || ext.Equals(".jpeg", StringComparison.OrdinalIgnoreCase)
                || ext.Equals(".webp", StringComparison.OrdinalIgnoreCase);
        }

        static FaceBook? TryReadCache(string path, string signature, Dictionary<string, string> names)
        {
            try
            {
                if (!File.Exists(path))
                {
                    return null;
                }

                using var stream = File.OpenRead(path);
                using var reader = new BinaryReader(stream);
                if (reader.ReadString() != signature)
                {
                    return null;
                }

                int count = reader.ReadInt32();
                var faces = new Face[count];
                for (int i = 0; i < count; i++)
                {
                    string id = reader.ReadString();
                    int length = reader.ReadInt32();
                    var values = new float[length];
                    for (int n = 0; n < length; n++)
                    {
                        values[n] = reader.ReadSingle();
                    }

                    faces[i] = new Face(id, names.GetValueOrDefault(id, id), values);
                }

                return new FaceBook(faces);
            }
            catch
            {
                return null;
            }
        }

        static void TryWriteCache(string path, string signature, Face[] faces)
        {
            try
            {
                using var stream = File.Create(path);
                using var writer = new BinaryWriter(stream);
                writer.Write(signature);
                writer.Write(faces.Length);
                foreach (var face in faces)
                {
                    writer.Write(face.Id);
                    writer.Write(face.Values.Length);
                    foreach (float value in face.Values)
                    {
                        writer.Write(value);
                    }
                }
            }
            catch
            {
                /* 次回もう一度作る */
            }
        }

        static Bitmap? CropFace(Image image)
        {
            using var pixels = Pixels.From((Bitmap)image);
            return CropFace(pixels);
        }

        static Bitmap? CropFace(Pixels pixels)
        {
            int y0 = (int)(pixels.Height * 0.68);
            int y1 = (int)(pixels.Height * 0.96);
            int x0 = (int)(pixels.Width * 0.62);
            int minX = pixels.Width;
            int minY = pixels.Height;
            int maxX = 0;
            int maxY = 0;
            int count = 0;
            for (int y = y0; y < y1; y += 2)
            {
                for (int x = x0; x < pixels.Width; x += 2)
                {
                    pixels.Read(x, y, out int r, out int g, out int b);
                    if (r <= 200 || g <= 140 || b >= 120 || r <= b + 60)
                    {
                        continue;
                    }

                    count++;
                    minX = Math.Min(minX, x);
                    minY = Math.Min(minY, y);
                    maxX = Math.Max(maxX, x);
                    maxY = Math.Max(maxY, y);
                }
            }

            int bw = maxX - minX;
            int bh = maxY - minY;
            if (count < 150 || bw < pixels.Width * 0.12 || bh < pixels.Height * 0.05)
            {
                return null;
            }

            int left = minX + (int)(bw * 0.18);
            int top = minY + (int)(bh * 0.08);
            int right = minX + (int)(bw * 0.78);
            int bottom = minY + (int)(bh * 0.72);
            if (right <= left || bottom <= top)
            {
                return null;
            }

            var face = new Bitmap(right - left, bottom - top, PixelFormat.Format24bppRgb);
            using var graphics = Graphics.FromImage(face);
            graphics.DrawImage(pixels.Source, new Rectangle(0, 0, face.Width, face.Height), new Rectangle(left, top, right - left, bottom - top), GraphicsUnit.Pixel);
            return face;
        }

        static float[] Feature(Bitmap source)
        {
            using var color = new Bitmap(18, 18, PixelFormat.Format24bppRgb);
            using (var graphics = Graphics.FromImage(color))
            {
                graphics.InterpolationMode = InterpolationMode.HighQualityBilinear;
                graphics.DrawImage(source, 0, 0, 18, 18);
            }

            var values = new float[18 + 8 + 8 + 14 * 14];
            var hue = new float[18];
            var sat = new float[8];
            var val = new float[8];
            for (int y = 0; y < 18; y++)
            {
                for (int x = 0; x < 18; x++)
                {
                    var pixel = color.GetPixel(x, y);
                    RgbToHsv(pixel.R, pixel.G, pixel.B, out double h, out double s, out double v);
                    hue[Math.Clamp((int)(h * 18), 0, 17)]++;
                    sat[Math.Clamp((int)(s * 8), 0, 7)]++;
                    val[Math.Clamp((int)(v * 8), 0, 7)]++;
                }
            }

            float total = 18 * 18;
            for (int i = 0; i < hue.Length; i++)
            {
                values[i] = hue[i] / total;
            }

            for (int i = 0; i < sat.Length; i++)
            {
                values[18 + i] = sat[i] / total;
            }

            for (int i = 0; i < val.Length; i++)
            {
                values[26 + i] = val[i] / total;
            }

            using var gray = new Bitmap(14, 14, PixelFormat.Format24bppRgb);
            using (var graphics = Graphics.FromImage(gray))
            {
                graphics.InterpolationMode = InterpolationMode.HighQualityBilinear;
                graphics.DrawImage(source, 0, 0, 14, 14);
            }

            int offset = 34;
            double mean = 0;
            var luma = new float[14 * 14];
            int n = 0;
            for (int y = 0; y < 14; y++)
            {
                for (int x = 0; x < 14; x++)
                {
                    var pixel = gray.GetPixel(x, y);
                    luma[n] = (float)((0.299 * pixel.R + 0.587 * pixel.G + 0.114 * pixel.B) / 255.0);
                    mean += luma[n];
                    n++;
                }
            }

            mean /= luma.Length;
            for (int i = 0; i < luma.Length; i++)
            {
                values[offset + i] = luma[i] - (float)mean;
            }

            return values;
        }

        static double L1(float[] left, float[] right)
        {
            int count = Math.Min(left.Length, right.Length);
            if (count == 0)
            {
                return double.PositiveInfinity;
            }

            double sum = 0;
            for (int i = 0; i < count; i++)
            {
                sum += Math.Abs(left[i] - right[i]);
            }

            return sum / count;
        }
    }

    readonly record struct Face(string Id, string Name, float[] Values);

    internal sealed class Pixels : IDisposable
    {
        public int Width { get; }
        public int Height { get; }
        public Bitmap Source { get; }
        readonly byte[] bytes;
        readonly int stride;
        readonly bool owned;

        Pixels(Bitmap source, byte[] bytes, int stride, bool owned)
        {
            Source = source;
            Width = source.Width;
            Height = source.Height;
            this.bytes = bytes;
            this.stride = stride;
            this.owned = owned;
        }

        public static Pixels From(Bitmap image)
        {
            var rect = new Rectangle(0, 0, image.Width, image.Height);
            var data = image.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try
            {
                var bytes = new byte[data.Stride * image.Height];
                System.Runtime.InteropServices.Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
                return new Pixels(image, bytes, data.Stride, owned: false);
            }
            finally
            {
                image.UnlockBits(data);
            }
        }

        public void Read(int x, int y, out int r, out int g, out int b)
        {
            int i = y * stride + x * 4;
            b = bytes[i];
            g = bytes[i + 1];
            r = bytes[i + 2];
        }

        public void Dispose()
        {
            if (owned)
            {
                Source.Dispose();
            }
        }
    }
}
