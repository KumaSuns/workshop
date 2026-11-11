using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

namespace MirrorDisplay;

sealed class PrepBoard : Control
{
    static readonly string[] IconFiles =
    {
        "Score.png",
        "Coin.png",
        "Exp.png",
        "Time.png",
        "Bomb.png",
        "5over4.png",
        "Combo.png",
    };

    readonly Font nameFont = new("Yu Gothic UI", 18f, FontStyle.Bold, GraphicsUnit.Pixel);
    readonly Bitmap?[] bright = new Bitmap?[IconFiles.Length];
    readonly Bitmap?[] dim = new Bitmap?[IconFiles.Length];
    readonly bool[] on = new bool[IconFiles.Length];
    string tsum = "";

    public PrepBoard()
    {
        BackColor = Color.White;
        DoubleBuffered = true;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer, true);
    }

    public void LoadIcons(string? directory)
    {
        if (string.IsNullOrEmpty(directory))
        {
            return;
        }

        for (int i = 0; i < IconFiles.Length; i++)
        {
            string path = Path.Combine(directory, IconFiles[i]);
            if (!File.Exists(path))
            {
                continue;
            }

            using var opened = new Bitmap(path);
            bright[i] = new Bitmap(opened);
            dim[i] = Fade(opened);
        }

        Invalidate();
    }

    public void Show(string tsumName, ReadOnlySpan<bool> items)
    {
        bool changed = tsum != tsumName;
        tsum = tsumName;
        for (int i = 0; i < on.Length; i++)
        {
            bool next = i < items.Length && items[i];
            if (next == on[i])
            {
                continue;
            }

            on[i] = next;
            changed = true;
        }

        if (changed)
        {
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics;
        g.Clear(Color.White);
        var bounds = ClientRectangle;
        bounds.Width -= 1;
        bounds.Height -= 1;
        using (var pen = new Pen(Color.FromArgb(80, 255, 214)))
        {
            g.DrawRectangle(pen, bounds);
        }

        if (tsum.Length > 0)
        {
            using var brush = new SolidBrush(Color.FromArgb(20, 24, 32));
            using var format = new StringFormat { Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap };
            g.DrawString("使用ツム  " + tsum, nameFont, brush, new RectangleF(12, 6, Math.Max(1, Width - 24), 28), format);
        }

        int count = IconFiles.Length;
        int icon = 56;
        int gap = 6;
        int rowWidth = count * icon + (count - 1) * gap;
        int x = Math.Max(8, (Width - rowWidth) / 2);
        int y = 40;
        for (int i = 0; i < count; i++)
        {
            var image = on[i] ? bright[i] : dim[i];
            var rect = new Rectangle(x, y, icon, icon);
            if (image != null)
            {
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.DrawImage(image, rect);
            }

            if (on[i])
            {
                using var glow = new Pen(Color.FromArgb(255, 196, 40), 3);
                g.DrawRectangle(glow, rect.X + 1, rect.Y + 1, rect.Width - 3, rect.Height - 3);
            }

            x += icon + gap;
        }
    }

    static Bitmap Fade(Bitmap source)
    {
        var faded = new Bitmap(source.Width, source.Height, PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(faded);
        var matrix = new ColorMatrix(new[]
        {
            new[] { 0.35f, 0f, 0f, 0f, 0f },
            new[] { 0f, 0.35f, 0f, 0f, 0f },
            new[] { 0f, 0f, 0.35f, 0f, 0f },
            new[] { 0f, 0f, 0f, 1f, 0f },
            new[] { 0.62f, 0.62f, 0.62f, 0f, 1f },
        });
        using var attributes = new ImageAttributes();
        attributes.SetColorMatrix(matrix);
        g.DrawImage(
            source,
            new Rectangle(0, 0, source.Width, source.Height),
            0,
            0,
            source.Width,
            source.Height,
            GraphicsUnit.Pixel,
            attributes);
        return faded;
    }
}
