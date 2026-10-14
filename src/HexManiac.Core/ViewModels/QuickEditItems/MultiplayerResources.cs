using System;
using System.IO;

namespace HavenSoft.HexManiac.Core.ViewModels.QuickEditItems {
   /// <summary>Where the built-in Emerald multiplayer BPS patch is loaded from.</summary>
   public interface IMultiplayerResources {
      /// <summary>The gzip-compressed BPS patch, or null when the patch has not been packaged.</summary>
      byte[] ReadPatch();

      /// <summary>Expected location of the patch, used in error messages.</summary>
      string Location { get; }
   }

   /// <summary>
   /// Loads the generated multiplayer patch from the application's resources folder.
   /// The patch is optional during development and is added after the game-side implementation is built.
   /// </summary>
   public sealed class ShippedMultiplayerResources : IMultiplayerResources {
      public const string PatchFileName = "multiplayer_emerald.bps.gz";
      private readonly string folder;

      /// <param name="folder">Defaults to the resources folder next to the application.</param>
      public ShippedMultiplayerResources(string folder = null) {
         this.folder = folder ?? Path.Combine(AppContext.BaseDirectory, "resources");
      }

      public string Location => Path.GetFullPath(folder);

      public byte[] ReadPatch() {
         var path = Path.Combine(folder, PatchFileName);
         return File.Exists(path) ? File.ReadAllBytes(path) : null;
      }
   }
}
