using HavenSoft.HexManiac.Core.Models;
using System;
using System.IO;
using System.Threading.Tasks;

namespace HavenSoft.HexManiac.Core.ViewModels.QuickEditItems {
   /// <summary>
   /// Utilities &gt; Misc &gt; "Apply Emerald Multiplayer".
   /// Applies a bundled BPS patch to the exact, unmodified English Pokemon Emerald v1.0 ROM.
   /// The generated patch adds the game-side features required for local GBA link multiplayer.
   /// </summary>
   public sealed class ApplyMultiplayerPatch : IQuickEditItem {
      private readonly EditorViewModel editor;
      private readonly IMultiplayerResources resources;
      private readonly VanillaRomSpec vanilla;
      private bool running, statusShown;

      private bool patchRead;
      private byte[] patch;
      private BpsInfo patchInfo;
      private string patchError;

      // CanRun is queried on tab switches and edits, so cache the last ROM check without retaining a closed tab's 16 MB image.
      private WeakReference<byte[]> checkedData;
      private long checkedStamp;
      private bool checkedResult;

      public string Name => "Apply Emerald Multiplayer";

      public string Description => @"Applies the local multiplayer-enabled Emerald patch to the ROM open in this tab.

Requires an unmodified Pokemon Emerald (USA, Europe) v1.0 ROM (BPEE, 16 MB). The patch is built for that exact ROM; edited, expanded, already-patched, or different-region ROMs are not accepted.

For multiplayer sessions in mGBA, each player also needs a matching generated link script. CUBHMA packages these when available as resources\multiplayer\inject.local-server.lua and resources\multiplayer\inject.local-client.lua. Open the patched ROM in two mGBA instances, enter the overworld, then load the server script in the first instance and the client script in the second.

Applying the patch replaces the contents of this tab but does not write to disk immediately. Use File > Save As to keep your original ROM untouched. Close the changed tab without saving to return to the original.

The menu item stays disabled in development builds until 'multiplayer_emerald.bps.gz' is built and included in the application's resources folder.";

      public string WikiLink => "https://github.com/ComicCheaps/CUBHMA-Multiplayer";

      public event EventHandler CanRunChanged;

      public ApplyMultiplayerPatch(EditorViewModel editor, IMultiplayerResources resources = null, VanillaRomSpec vanilla = null) {
         this.editor = editor;
         this.resources = resources ?? new ShippedMultiplayerResources();
         this.vanilla = vanilla ?? VanillaRomSpec.EmeraldUsV10;
      }

      /// <summary>
      /// True only when an open tab is the exact source ROM required by the bundled multiplayer patch.
      /// The BPS header and ROM size are checked before reading the full ROM checksum.
      /// </summary>
      public bool CanRun(IViewPort viewPort) {
         if (viewPort is not ViewPort tab) return false;
         var data = tab.Model?.RawData;
         if (data == null || data.Length != vanilla.Length) return false;
         if (EmeraldRomCheck.ReadGameCode(data) != vanilla.GameCode) return false;

         LoadPatch();
         if (patchInfo == null) return false;

         var stamp = ModelEditStamp.Current;
         if (stamp == checkedStamp && checkedData != null && checkedData.TryGetTarget(out var known) && ReferenceEquals(data, known)) return checkedResult;

         var result = (uint)Patcher.CalcCRC32(data) == vanilla.Crc32;
         checkedData = new WeakReference<byte[]>(data);
         checkedStamp = stamp;
         checkedResult = result;
         return result;
      }

      public void TabChanged() => CanRunChanged?.Invoke(this, EventArgs.Empty);

      public async Task<ErrorInfo> Run(IViewPort viewPort) {
         if (running) return new ErrorInfo("Emerald Multiplayer is already being applied.", isWarningLevel: true);
         running = true;
         statusShown = false;
         ErrorInfo result;
         try {
            result = await RunInternal(viewPort);
         } catch (Exception ex) {
            result = new ErrorInfo("Could not apply Emerald Multiplayer: " + ex.Message);
         } finally {
            running = false;
         }

         if (statusShown && !(result.HasError && result.IsWarning)) editor.ShowStatus(string.Empty);
         return result;
      }

      private async Task<ErrorInfo> RunInternal(IViewPort viewPort) {
         var dispatcher = editor.Singletons.WorkDispatcher;
         if (viewPort is not ViewPort tab || tab.Model == null) {
            return new ErrorInfo("Apply Emerald Multiplayer works on the ROM open in the current tab. Open an unmodified Pokemon Emerald (USA, Europe) v1.0 ROM first.");
         }

         await dispatcher.WaitForRenderingAsync();

         LoadPatch();
         if (patchInfo == null) {
            return new ErrorInfo(patchError ?? "The Emerald Multiplayer patch is not available.");
         }

         var data = tab.Model.RawData;
         var check = EmeraldRomCheck.Check(data, vanilla, patchInfo);
         if (!check.IsVanilla) return new ErrorInfo(check.Message);

         if (!tab.ChangeHistory.IsSaved) {
            return new ErrorInfo(
               "This tab has unsaved changes. Applying Emerald Multiplayer replaces the contents of the tab, so save your work first or close this tab and reopen the original ROM.");
         }

         var sourceCrc = Patcher.CalcCRC32(data);
         var source = (byte[])data.Clone();
         statusShown = true;
         editor.ShowStatus($"Applying Emerald Multiplayer to {Path.GetFileName(tab.FileName)} ({FormatMegabytes(patchInfo.TargetSize)}), this takes a few seconds...");

         BpsApplyResult applied = null;
         await dispatcher.RunBackgroundWork(() => applied = BpsPatch.Apply(patch, source));
         if (applied == null) return new ErrorInfo("The multiplayer patch did not finish applying.");
         if (!applied.Success) return new ErrorInfo("Could not apply Emerald Multiplayer: " + applied.Message);

         if (!ReferenceEquals(tab.Model.RawData, data) || Patcher.CalcCRC32(tab.Model.RawData) != sourceCrc || !tab.ChangeHistory.IsSaved) {
            return new ErrorInfo("The ROM in this tab changed while the multiplayer patch was being built, so nothing was applied. Run the tool again.");
         }

         var fileName = Path.GetFileName(tab.FileName);
         var multiplayerTab = editor.ReplaceRomTab(tab, applied.Target, Array.Empty<string>());
         if (multiplayerTab == null) return new ErrorInfo("The ROM tab was closed while the multiplayer patch was being applied, so nothing was changed.");

         return new ErrorInfo(
            $"Applied the Emerald Multiplayer patch to {fileName} ({FormatMegabytes(applied.Target.Length)}). It is not saved yet: use File > Save As to keep the original ROM untouched, or close this tab without saving to return to the original.",
            isWarningLevel: true);
      }

      private void LoadPatch() {
         if (patchRead) return;
         patchRead = true;

         try {
            var compressed = resources.ReadPatch();
            if (compressed == null) {
               patchError =
                  $"The Emerald Multiplayer patch is not bundled yet. Expected '{ShippedMultiplayerResources.PatchFileName}' in{Environment.NewLine}" +
                  $"{resources.Location}{Environment.NewLine}" +
                  "The game-side multiplayer implementation must be built into a BPS patch before this tool can be enabled.";
               return;
            }

            patch = BpsPatch.DecompressIfGzip(compressed);
            patchInfo = BpsPatch.ReadInfo(patch);
            if (patchInfo == null) {
               patchError = "The bundled Emerald Multiplayer patch is damaged or is not a valid BPS patch.";
               return;
            }

            if (patchInfo.SourceSize != vanilla.Length || patchInfo.SourceCrc32 != vanilla.Crc32) {
               patchInfo = null;
               patchError = $"The bundled multiplayer patch was built for a different base ROM. It must target {vanilla.Name}.";
            }
         } catch (Exception ex) {
            patchInfo = null;
            patchError = "Could not read the bundled Emerald Multiplayer patch: " + ex.Message;
         }
      }

      private static string FormatMegabytes(long length) => length >= (1 << 20) ? $"{length / (double)(1 << 20):0.#} MB" : $"{length:N0} bytes";
   }
}
