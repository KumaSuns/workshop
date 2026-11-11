using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace MirrorDisplay;

static class StartScreen
{
    public const string SplashText = "起動画面";
    public const string TitleText = "ゲームスタート";

    public static string? Match(Image image)
    {
        if (image.Width < 8 || image.Height <= image.Width)
        {
            return null;
        }

        using var small = new Bitmap(48, 104, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(small))
        {
            graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.Low;
            graphics.DrawImage(image, new Rectangle(0, 0, small.Width, small.Height));
        }

        var all = Count(small, 0, 1);
        var line = Count(small, 0.24, 0.38);
        var play = Count(small, 0.42, 0.58);
        var top = Count(small, 0, 0.18);
        var bottom = Count(small, 0.84, 1);
        var chars = Count(small, 0.48, 0.75);
        var logo = Count(small, 0.22, 0.40);
        var button = Count(small, 0.73, 0.84);

        if (all.White > 0.82 && line.Green > 0.10 && play.Sat > 0.08 && button.Yellow < 0.05)
        {
            return SplashText;
        }

        if (top.White > 0.90 && bottom.White > 0.90 && button.Yellow > 0.12 && chars.Sat > 0.20 && logo.Sat > 0.15)
        {
            return TitleText;
        }

        return null;
    }

    readonly struct Band
    {
        public Band(int count, int white, int sat, int yellow, int green)
        {
            Count = count;
            White = count == 0 ? 0 : white / (double)count;
            Sat = count == 0 ? 0 : sat / (double)count;
            Yellow = count == 0 ? 0 : yellow / (double)count;
            Green = count == 0 ? 0 : green / (double)count;
        }

        public int Count { get; }
        public double White { get; }
        public double Sat { get; }
        public double Yellow { get; }
        public double Green { get; }
    }

    static Band Count(Bitmap image, double y0, double y1)
    {
        int top = (int)(image.Height * y0);
        int bottom = Math.Max(top + 1, (int)(image.Height * y1));
        var rect = new Rectangle(0, 0, image.Width, image.Height);
        var data = image.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        try
        {
            int stride = data.Stride;
            var bytes = new byte[stride * image.Height];
            Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
            int count = 0;
            int white = 0;
            int sat = 0;
            int yellow = 0;
            int green = 0;
            for (int y = top; y < bottom; y++)
            {
                int row = y * stride;
                for (int x = 0; x < image.Width; x++)
                {
                    int i = row + x * 3;
                    int b = bytes[i];
                    int g = bytes[i + 1];
                    int r = bytes[i + 2];
                    int max = Math.Max(r, Math.Max(g, b));
                    int min = Math.Min(r, Math.Min(g, b));
                    count++;
                    if (r > 230 && g > 230 && b > 230)
                    {
                        white++;
                    }

                    if (max - min > 40 && max > 80)
                    {
                        sat++;
                    }

                    if (r > 180 && g > 140 && b < 90 && r > b + 60)
                    {
                        yellow++;
                    }

                    if (g > r + 30 && g > b + 20 && g > 80)
                    {
                        green++;
                    }
                }
            }

            return new Band(count, white, sat, yellow, green);
        }
        finally
        {
            image.UnlockBits(data);
        }
    }
}
