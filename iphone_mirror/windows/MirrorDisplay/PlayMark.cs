using System.Drawing.Imaging;

namespace MirrorDisplay;

static class PlayMark
{
    public static string Match(Bitmap image)
    {
        if (image.Width < 8 || image.Height <= image.Width)
        {
            return "";
        }

        var word = Count(image, 0.18, 0.28, 0.82, 0.50);
        var lower = Count(image, 0.18, 0.50, 0.82, 0.74);
        if (word.Total == 0 || lower.Total == 0)
        {
            return "";
        }

        double cyan = word.Cyan / (double)word.Total;
        double pink = word.Pink / (double)word.Total;
        double dark = word.Dark / (double)word.Total;
        double blue = word.Blue / (double)word.Total;
        double lowerBlue = lower.Blue / (double)lower.Total;
        double lowerDark = lower.Dark / (double)lower.Total;
        if (cyan >= 0.10 && blue >= 0.80 && pink < 0.04 && dark < 0.45 && lowerBlue >= 0.90 && lowerDark >= 0.55)
        {
            return "go";
        }

        if (TimeUp(image))
        {
            return "timeup";
        }

        return "";
    }

    static bool TimeUp(Bitmap image)
    {
        const int strips = 16;
        var ratios = new double[strips, 5];
        var samples = new int[strips];
        var rect = new Rectangle(0, 0, image.Width, image.Height);
        var data = image.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        int xSteps = 0;
        int[] coreCols = Array.Empty<int>();
        try
        {
            int stride = data.Stride;
            var bytes = new byte[stride * image.Height];
            System.Runtime.InteropServices.Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
            int x0 = (int)(image.Width * 0.12);
            int x1 = (int)(image.Width * 0.88);
            for (int x = x0; x < x1; x += 3)
            {
                xSteps++;
            }

            coreCols = new int[strips * Math.Max(xSteps, 1)];
            for (int i = 0; i < strips; i++)
            {
                int y0 = image.Height * i / strips;
                int y1 = image.Height * (i + 1) / strips;
                int cyan = 0;
                int dark = 0;
                int blue = 0;
                int bright = 0;
                int core = 0;
                int total = 0;
                int rows = 0;
                for (int y = y0; y < y1; y += 3)
                {
                    int row = y * stride;
                    int col = 0;
                    rows++;
                    for (int x = x0; x < x1; x += 3)
                    {
                        int p = row + x * 4;
                        int b = bytes[p];
                        int g = bytes[p + 1];
                        int r = bytes[p + 2];
                        total++;
                        if (b > 160 && g > 140 && b > r + 10 && g + 20 > r)
                        {
                            cyan++;
                        }

                        if (r < 80 && g < 100 && b < 140)
                        {
                            dark++;
                        }

                        if (b > r + 30 && b > g && b > 90 && r < 140)
                        {
                            blue++;
                        }

                        if (r + g + b > 500)
                        {
                            bright++;
                        }

                        if (b > 180 && g > 170 && r > 120 && b > r && g > r - 10)
                        {
                            core++;
                            coreCols[i * xSteps + col]++;
                        }

                        col++;
                    }
                }

                samples[i] = rows;
                if (total == 0)
                {
                    continue;
                }

                ratios[i, 0] = cyan / (double)total;
                ratios[i, 1] = dark / (double)total;
                ratios[i, 2] = blue / (double)total;
                ratios[i, 3] = bright / (double)total;
                ratios[i, 4] = core / (double)total;
            }
        }
        finally
        {
            image.UnlockBits(data);
        }

        for (int i = 0; i < strips; i++)
        {
            double y0 = i / (double)strips;
            if (y0 < 0.18 || y0 > 0.55)
            {
                continue;
            }

            if (ratios[i, 0] < 0.18 || ratios[i, 3] < 0.12 || ratios[i, 4] < 0.15)
            {
                continue;
            }

            if (samples[i] == 0 || xSteps == 0)
            {
                continue;
            }

            int marked = 0;
            for (int col = 0; col < xSteps; col++)
            {
                if (coreCols[i * xSteps + col] / (double)samples[i] > 0.08)
                {
                    marked++;
                }
            }

            if (marked / (double)xSteps < 0.48)
            {
                continue;
            }

            int run = 0;
            for (int j = i + 1; j < strips && j / (double)strips < 0.84; j++)
            {
                if (ratios[j, 1] < 0.80 || ratios[j, 2] >= 0.30)
                {
                    break;
                }

                run++;
            }

            if (run >= 4)
            {
                return true;
            }
        }

        return false;
    }

    readonly struct Band
    {
        public Band(int total, int pink, int cyan, int dark, int blue)
        {
            Total = total;
            Pink = pink;
            Cyan = cyan;
            Dark = dark;
            Blue = blue;
        }

        public int Total { get; }
        public int Pink { get; }
        public int Cyan { get; }
        public int Dark { get; }
        public int Blue { get; }
    }

    static Band Count(Bitmap image, double x0, double y0, double x1, double y1)
    {
        int left = Math.Clamp((int)(image.Width * x0), 0, image.Width - 1);
        int top = Math.Clamp((int)(image.Height * y0), 0, image.Height - 1);
        int right = Math.Clamp((int)(image.Width * x1), left + 1, image.Width);
        int bottom = Math.Clamp((int)(image.Height * y1), top + 1, image.Height);
        using var small = new Bitmap(40, 16, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(small))
        {
            graphics.DrawImage(
                image,
                new Rectangle(0, 0, small.Width, small.Height),
                new Rectangle(left, top, right - left, bottom - top),
                GraphicsUnit.Pixel);
        }

        int pink = 0;
        int cyan = 0;
        int dark = 0;
        int blue = 0;
        for (int y = 0; y < small.Height; y++)
        {
            for (int x = 0; x < small.Width; x++)
            {
                var pixel = small.GetPixel(x, y);
                int r = pixel.R;
                int g = pixel.G;
                int b = pixel.B;
                if (r > 180 && b > 140 && g < 160 && r > g + 40)
                {
                    pink++;
                }

                if (g > 150 && b > 170 && r < 190 && b > r + 15 && g > r)
                {
                    cyan++;
                }

                if (r < 70 && g < 90 && b < 120)
                {
                    dark++;
                }

                if (b > r + 30 && b > g && b > 80 && r < 120)
                {
                    blue++;
                }
            }
        }

        return new Band(small.Width * small.Height, pink, cyan, dark, blue);
    }
}
